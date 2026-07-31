"""Matching metrics: population-weighted structural profiles, SMD, and the
Weighted Structural Distance objective.

Pure functions (no Streamlit).  The live app keeps thin cached wrappers around
``calculate_metrics_from_flat`` / ``preprocess_data``; the package versions are
decorator-free so the matching core stays importable without Streamlit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import POPULATION_COL
from .structural import impute_missing_features


def weighted_profile(
    df: pd.DataFrame, features: list[str], population_col: str = POPULATION_COL
) -> pd.Series:
    """Population-weighted feature means. Falls back to equal-weighted means
    if the population column is missing, all-NaN, or sums to zero/negative."""
    if population_col in df.columns:
        w = pd.to_numeric(df[population_col], errors="coerce")
        if w.notna().any() and w.fillna(0).sum() > 0:
            w = w.fillna(0).values
            return pd.Series(
                {f: np.average(df[f].values, weights=w) for f in features}, index=features
            )
    return df[features].mean()


def fit_structural_stats(eligible_df: pd.DataFrame, features: list[str]):
    """Fit ONE structural mean/std basis on the eligible region universe
    (selected test regions + full control candidate pool) for this run.
    Using the same basis for every candidate group is what makes
    Weighted Structural Distance comparable across candidates of different sizes."""
    means = eligible_df[features].mean()
    stds = eligible_df[features].std(ddof=0)
    return means, stds


def calculate_metrics(
    test_df,
    control_df,
    features,
    weights_dict,
    eligible_means,
    eligible_stds,
    population_col=POPULATION_COL,
):
    """
    eligible_means / eligible_stds: dict-like {feature: value}, fitted ONCE per run
    via fit_structural_stats() on the eligible region universe — NOT refit per candidate.
    Returns a dict (not an ambiguous tuple).
    """
    empty = {
        "mean_abs_smd": 0.0,
        "weighted_structural_distance": 0.0,
        "smd_list": [],
        "test_means": np.array([]),
        "control_means": np.array([]),
        "raw_diffs": np.array([]),
        "weighted_contributions": np.array([]),
    }
    if not features:
        return empty
    test_df = impute_missing_features(test_df, features)
    control_df = impute_missing_features(control_df, features)
    # Guard: only use features present in both dataframes
    features = [f for f in features if f in test_df.columns and f in control_df.columns]
    if not features:
        return empty

    # Population-weighted structural profiles (falls back to equal-weighted mean internally)
    test_profile = weighted_profile(test_df, features, population_col)
    control_profile = weighted_profile(control_df, features, population_col)

    means_arr = np.array([eligible_means[f] for f in features], dtype=float)
    stds_arr = np.array([eligible_stds[f] for f in features], dtype=float)
    # Safe denominator for z-scoring only (never divide by 0); SMD uses the raw stds_arr below.
    z_scale = np.where((stds_arr > 0) & np.isfinite(stds_arr), stds_arr, 1.0)

    z_test = (test_profile.values - means_arr) / z_scale
    z_control = (control_profile.values - means_arr) / z_scale

    w_vector = np.array([weights_dict.get(f, 1.0) for f in features])
    sq_diff = (z_test - z_control) ** 2
    # weighted_structural_distance is the slider-weighted optimisation metric, scored on the
    # fixed eligible-pool basis so it is comparable across candidate groups of different sizes.
    weighted_contributions = w_vector * sq_diff
    weighted_structural_distance = float(np.sqrt(np.sum(weighted_contributions)))

    raw_diffs = test_profile.values - control_profile.values

    # mean_abs_smd is the unweighted diagnostic balance metric (no slider weights),
    # using the FULL eligible pool's std as a stable denominator — not the selected
    # group's own std, which can be 0 (or near-0) with a single test/control region.
    smd_list = []
    for i, f in enumerate(features):
        feature_scale = stds_arr[i]
        if feature_scale > 0 and np.isfinite(feature_scale):
            smd_list.append(abs(raw_diffs[i] / feature_scale))
        else:
            smd_list.append(
                np.nan
            )  # flagged: feature has zero/invalid variance across the eligible pool
    mean_abs_smd = float(np.nanmean(smd_list)) if smd_list else 0.0

    return {
        "mean_abs_smd": mean_abs_smd,
        "weighted_structural_distance": weighted_structural_distance,
        "smd_list": smd_list,
        "test_means": test_profile.values,
        "control_means": control_profile.values,
        "raw_diffs": raw_diffs,
        "weighted_contributions": weighted_contributions,
    }


def calculate_metrics_from_flat(
    test_df,
    control_df,
    features_tuple,
    weights_tuple,
    eligible_means_tuple,
    eligible_stds_tuple,
):
    """Pure, decorator-free version of the app's cached ``calculate_metrics_cached``:
    accepts hashable tuple inputs and delegates to ``calculate_metrics``."""
    features = list(features_tuple)
    weights_dict = dict(zip(features, weights_tuple))
    eligible_means = dict(zip(features, eligible_means_tuple))
    eligible_stds = dict(zip(features, eligible_stds_tuple))
    return calculate_metrics(
        test_df, control_df, features, weights_dict, eligible_means, eligible_stds
    )


def make_fast_metrics_fn(
    pool_df,
    test_df_run,
    features,
    weights_dict,
    eligible_means,
    eligible_stds,
    population_col=POPULATION_COL,
):
    """Builds a vectorised scorer for candidate control groups drawn from a FIXED pool.

    Returns fast_metrics(idx_list) -> the same dict calculate_metrics() produces, where
    idx_list contains pool_df index labels. The matching strategy loops call the metrics
    function hundreds to thousands of times per run; calculate_metrics() pays for two
    dataframe copies, per-feature median imputation (a no-op there — pool/test frames are
    already imputed upstream), and per-feature Python loops on EVERY call. Here all of
    that is hoisted: the feature matrix, population weights, eligible-basis arrays, and
    the (constant) test profile are computed once, and each candidate is scored with a
    handful of NumPy array ops.

    The test profile is computed with the same weighted_profile() helper that
    calculate_metrics() uses, and the control profile / SMD math mirrors it exactly, so
    scores are numerically equivalent."""
    features = [f for f in features if f in test_df_run.columns and f in pool_df.columns]
    pos_map = {label: i for i, label in enumerate(pool_df.index)}
    X = pool_df[features].to_numpy(dtype=float) if features else np.empty((len(pool_df), 0))

    if population_col in pool_df.columns:
        _pop_raw = pd.to_numeric(pool_df[population_col], errors="coerce")
        pop_notna = _pop_raw.notna().to_numpy()
        pop_filled = _pop_raw.fillna(0).to_numpy(dtype=float)
    else:
        pop_notna = None
        pop_filled = None

    test_imputed = impute_missing_features(test_df_run, features)
    test_profile = (
        weighted_profile(test_imputed, features, population_col).values
        if features
        else np.array([])
    )

    means_arr = np.array([eligible_means[f] for f in features], dtype=float)
    stds_arr = np.array([eligible_stds[f] for f in features], dtype=float)
    z_scale = np.where((stds_arr > 0) & np.isfinite(stds_arr), stds_arr, 1.0)
    z_test = (test_profile - means_arr) / z_scale if features else np.array([])
    w_vector = np.array([weights_dict.get(f, 1.0) for f in features])
    valid_std = (stds_arr > 0) & np.isfinite(stds_arr)
    safe_stds = np.where(valid_std, stds_arr, 1.0)

    def fast_metrics(idx_list):
        # Rare edge cases (no features / empty candidate group) defer to the reference
        # implementation so behaviour is identical.
        if not features or len(idx_list) == 0:
            return calculate_metrics(
                test_df_run,
                pool_df.loc[list(idx_list)],
                features,
                weights_dict,
                eligible_means,
                eligible_stds,
                population_col,
            )
        rows = [pos_map[i] for i in idx_list]
        Xg = X[rows]
        # Population-weighted control profile, with the same equal-weight fallback
        # weighted_profile() applies when population is missing or sums to zero.
        if pop_filled is not None and pop_notna[rows].any() and pop_filled[rows].sum() > 0:
            w = pop_filled[rows]
            control_profile = (Xg * w[:, None]).sum(axis=0) / w.sum()
        else:
            control_profile = Xg.mean(axis=0)

        z_control = (control_profile - means_arr) / z_scale
        sq_diff = (z_test - z_control) ** 2
        weighted_contributions = w_vector * sq_diff
        weighted_structural_distance = float(np.sqrt(np.sum(weighted_contributions)))

        raw_diffs = test_profile - control_profile
        smd_arr = np.where(valid_std, np.abs(raw_diffs) / safe_stds, np.nan)
        mean_abs_smd = (
            float(np.nanmean(smd_arr))
            if smd_arr.size and not np.isnan(smd_arr).all()
            else (float("nan") if smd_arr.size else 0.0)
        )

        return {
            "mean_abs_smd": mean_abs_smd,
            "weighted_structural_distance": weighted_structural_distance,
            "smd_list": smd_arr.tolist(),
            "test_means": test_profile.copy(),
            "control_means": control_profile,
            "raw_diffs": raw_diffs,
            "weighted_contributions": weighted_contributions,
        }

    return fast_metrics


def preprocess_data(
    pool_df, test_df_run, active_features, weights, eligible_means_tuple, eligible_stds_tuple
):
    """Nearest-neighbour candidate search uses the SAME fixed eligible-pool basis
    (eligible_means/eligible_stds) as calculate_metrics(), so the NN ranking is
    consistent with the Weighted Structural Distance objective."""
    pool_df = impute_missing_features(pool_df, active_features)
    test_df_run = impute_missing_features(test_df_run, active_features)
    means_arr = np.array(eligible_means_tuple, dtype=float)
    stds_arr = np.array(eligible_stds_tuple, dtype=float)
    z_scale = np.where((stds_arr > 0) & np.isfinite(stds_arr), stds_arr, 1.0)
    w_vec = np.array([np.sqrt(weights.get(f, 1.0)) for f in active_features])
    p_scaled = ((pool_df[active_features].values - means_arr) / z_scale) * w_vec
    t_profile = weighted_profile(test_df_run, active_features, POPULATION_COL).values
    t_cent = (((t_profile - means_arr) / z_scale) * w_vec).reshape(1, -1)
    return w_vec, p_scaled, t_cent


def calculate_experiment_population_coverage(test_regions, agg_df, geo_col, total_market_pop):
    if total_market_pop <= 0 or not test_regions:
        return 0.0
    test_pop = agg_df[agg_df[geo_col].isin(test_regions)][POPULATION_COL].sum()
    return (test_pop / total_market_pop) * 100
