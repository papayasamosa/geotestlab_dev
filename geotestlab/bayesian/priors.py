"""Prior parameter construction: structurally informed and standard weak priors."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from geotestlab.bayesian.models import PriorSpec
from geotestlab.matching import impute_missing_features

_STANDARD_SIGMA = 0.5
_DEFAULT_MIN_SIGMA = 0.25
_DEFAULT_MAX_SIGMA = 0.70


def calculate_structural_prior_sigmas(
    agg_df,
    test_regions,
    control_regions,
    geo_col,
    feature_cols,
    weight_dict=None,
    population_col="Population",
    min_sigma=0.25,
    max_sigma=0.70,
):
    """
    Compute per-control coefficient prior sigmas based on structural similarity
    to the population-weighted test-group profile.

    Returns
    -------
    prior_sigmas : np.ndarray  shape (len(control_regions),)
    structural_prior_df : pd.DataFrame
    """
    # 1. Keep only features present in agg_df and numeric
    valid_features = [
        f for f in feature_cols if f in agg_df.columns and pd.api.types.is_numeric_dtype(agg_df[f])
    ]

    # Edge case: no valid features
    if not valid_features:
        prior_sigmas = np.repeat(_STANDARD_SIGMA, len(control_regions))
        df_out = pd.DataFrame(
            {
                "Control Region": control_regions,
                "Structural Distance": np.nan,
                "Structural Similarity": np.nan,
                "Prior Sigma": prior_sigmas,
                "Prior Type": "Standard weak prior",
            }
        )
        return prior_sigmas, df_out

    # 2. Impute missing values if helper is available
    try:
        agg_df = impute_missing_features(agg_df, valid_features)
    except Exception:
        pass

    # 3. Standardise across all available regions
    all_regions = list(test_regions) + list(control_regions)
    region_df = agg_df[agg_df[geo_col].isin(all_regions)].copy()
    region_df = region_df.drop_duplicates(subset=[geo_col])

    scaler = StandardScaler()
    try:
        region_df[valid_features] = scaler.fit_transform(region_df[valid_features].fillna(0))
    except Exception:
        prior_sigmas = np.repeat(_STANDARD_SIGMA, len(control_regions))
        df_out = pd.DataFrame(
            {
                "Control Region": control_regions,
                "Structural Distance": np.nan,
                "Structural Similarity": np.nan,
                "Prior Sigma": prior_sigmas,
                "Prior Type": "Standard weak prior",
            }
        )
        return prior_sigmas, df_out

    # 4. Population-weighted test-group profile
    test_rows = region_df[region_df[geo_col].isin(test_regions)]
    if population_col in test_rows.columns:
        pop_weights = pd.to_numeric(test_rows[population_col], errors="coerce").fillna(1.0).values
        if pop_weights.sum() <= 0 or np.isnan(pop_weights).all():
            pop_weights = np.ones(len(test_rows))
    else:
        pop_weights = np.ones(len(test_rows))

    test_features = test_rows[valid_features].values
    if len(test_features) == 0:
        prior_sigmas = np.repeat(_STANDARD_SIGMA, len(control_regions))
        df_out = pd.DataFrame(
            {
                "Control Region": control_regions,
                "Structural Distance": np.nan,
                "Structural Similarity": np.nan,
                "Prior Sigma": prior_sigmas,
                "Prior Type": "Standard weak prior",
            }
        )
        return prior_sigmas, df_out

    test_profile_z = np.average(test_features, axis=0, weights=pop_weights)

    # 5. Feature weights
    if weight_dict is not None:
        feature_weights = np.array([weight_dict.get(f, 1.0) for f in valid_features], dtype=float)
        feature_weights = np.where(feature_weights <= 0, 1.0, feature_weights)
    else:
        feature_weights = np.ones(len(valid_features))
    feature_weights = feature_weights / feature_weights.sum()

    # 6. Distance and similarity for each control
    distances = []
    for ctrl in control_regions:
        ctrl_row = region_df[region_df[geo_col] == ctrl]
        if ctrl_row.empty:
            distances.append(np.nan)
        else:
            ctrl_z = ctrl_row[valid_features].values[0]
            dist = np.sqrt(np.average((ctrl_z - test_profile_z) ** 2, weights=feature_weights))
            distances.append(dist)

    distances = np.array(distances, dtype=float)
    # Replace NaN distances with max observed distance (worst case)
    finite_mask = np.isfinite(distances)
    if finite_mask.any():
        distances = np.where(finite_mask, distances, np.nanmax(distances))
    else:
        # All NaN — fall back to uniform
        prior_sigmas = np.repeat(_STANDARD_SIGMA, len(control_regions))
        df_out = pd.DataFrame(
            {
                "Control Region": control_regions,
                "Structural Distance": np.nan,
                "Structural Similarity": np.nan,
                "Prior Sigma": prior_sigmas,
                "Prior Type": "Standard weak prior",
            }
        )
        return prior_sigmas, df_out

    similarities = 1.0 / (1.0 + distances)

    # 7. Edge case: single control or all similarities identical
    if len(control_regions) == 1 or (similarities.max() - similarities.min()) < 1e-8:
        prior_sigmas = np.repeat(_STANDARD_SIGMA, len(control_regions))
        df_out = pd.DataFrame(
            {
                "Control Region": control_regions,
                "Structural Distance": np.round(distances, 3),
                "Structural Similarity": np.round(similarities, 3),
                "Prior Sigma": np.round(prior_sigmas, 3),
                "Prior Type": "Standard weak prior",
            }
        )
        return prior_sigmas, df_out

    # 8. Continuous scaling to [min_sigma, max_sigma]
    similarity_scaled = (similarities - similarities.min()) / (
        similarities.max() - similarities.min() + 1e-8
    )
    prior_sigmas = min_sigma + similarity_scaled * (max_sigma - min_sigma)
    prior_sigmas = np.clip(prior_sigmas, min_sigma, max_sigma)

    prior_types = ["Structurally informed" for _ in control_regions]

    df_out = pd.DataFrame(
        {
            "Control Region": control_regions,
            "Structural Distance": np.round(distances, 3),
            "Structural Similarity": np.round(similarities, 3),
            "Prior Sigma": np.round(prior_sigmas, 3),
            "Prior Type": prior_types,
        }
    )

    return prior_sigmas.astype(float), df_out


def compute_correlation_sigma_bounds(X_pre, y_pre):
    """Data-driven prior-sigma bounds from pre-period KPI correlations.

    corr[i] = how well control i tracks the test KPI historically. The median
    absolute correlation anchors the midpoint; bounds scale with the data
    (better-tracking controls -> higher sigma ceiling; weaker -> tighter floor).
    Falls back to (0.25, 0.70) on any numerical failure or empty input.
    """
    if X_pre is None or y_pre is None or len(y_pre) == 0 or X_pre.shape[1] == 0:
        return _DEFAULT_MIN_SIGMA, _DEFAULT_MAX_SIGMA
    try:
        pre_corrs = np.array(
            [
                np.corrcoef(X_pre[:, i], y_pre)[0, 1] if np.std(X_pre[:, i]) > 0 else 0.0
                for i in range(X_pre.shape[1])
            ]
        )
        pre_corrs = np.nan_to_num(pre_corrs, nan=0.0)
        abs_corrs = np.abs(pre_corrs)
        # Median absolute correlation anchors the midpoint
        median_corr = float(np.median(abs_corrs))
        median_corr = np.clip(median_corr, 0.1, 0.95)
        # Bounds scale with the data: better-tracking controls
        # -> higher sigma ceiling; weaker -> tighter floor
        _min_sigma = round(float(np.clip(median_corr * 0.4, 0.10, 0.40)), 3)
        _max_sigma = round(float(np.clip(median_corr * 1.2, 0.30, 0.90)), 3)
        return _min_sigma, _max_sigma
    except Exception:
        return _DEFAULT_MIN_SIGMA, _DEFAULT_MAX_SIGMA


def _same_period_label(frequency_config):
    return "Same day" if frequency_config["frequency"] == "daily" else "Same week"


def _lag_term_label(lag_periods, frequency_config):
    return f"Lag {lag_periods} " + (
        frequency_config["period_label_singular"]
        if lag_periods == 1
        else frequency_config["period_label_plural"]
    )


def _standard_prior_rows(control_list, feature_cols, lag_periods, frequency_config):
    """Standard weak prior table (all 0.5 sigmas) with per-feature rows."""
    if len(feature_cols) != len(control_list):
        # Lagged model: one same-period and one lagged row per control.
        rows = []
        for c in control_list:
            rows.append(
                {
                    "Feature": c,
                    "Control Region": c,
                    "Term Type": _same_period_label(frequency_config),
                    "Structural Distance": np.nan,
                    "Structural Similarity": np.nan,
                    "Prior Sigma": _STANDARD_SIGMA,
                    "Prior Type": "Standard weak prior",
                }
            )
        for c in control_list:
            rows.append(
                {
                    "Feature": f"{c}_lag{lag_periods}",
                    "Control Region": c,
                    "Term Type": _lag_term_label(lag_periods, frequency_config),
                    "Structural Distance": np.nan,
                    "Structural Similarity": np.nan,
                    "Prior Sigma": _STANDARD_SIGMA,
                    "Prior Type": "Standard weak prior",
                }
            )
        return pd.DataFrame(rows)
    return pd.DataFrame(
        {
            "Control Region": control_list,
            "Structural Distance": np.nan,
            "Structural Similarity": np.nan,
            "Prior Sigma": np.repeat(_STANDARD_SIGMA, len(control_list)),
            "Prior Type": "Standard weak prior",
        }
    )


def build_prior_spec(
    control_list,
    model_feature_cols,
    structural_feature_cols,
    include_lagged_controls,
    lag_periods,
    frequency_config,
    use_structural_priors,
    structural_agg_df,
    test_regions,
    geo_col,
    weight_dict=None,
    population_col="Population",
    X_pre=None,
    y_pre=None,
) -> PriorSpec:
    """Build the coefficient prior spec (sigmas + display table) for a Bayesian run.

    ``model_feature_cols`` are the model features (controls, plus lagged terms
    when lagging is enabled); ``structural_feature_cols`` are the matching
    features used to score structural similarity when priors are structurally
    informed. Mirrors the pre-extraction behaviour exactly.
    """
    if use_structural_priors:
        min_sigma, max_sigma = compute_correlation_sigma_bounds(X_pre, y_pre)
        prior_sigmas_base, structural_prior_df_base = calculate_structural_prior_sigmas(
            agg_df=structural_agg_df,
            test_regions=test_regions,
            control_regions=control_list,
            geo_col=geo_col,
            feature_cols=structural_feature_cols,
            weight_dict=weight_dict,
            population_col=population_col,
            min_sigma=min_sigma,
            max_sigma=max_sigma,
        )
        if include_lagged_controls:
            # Duplicate/map each base region's structural prior sigma to its
            # lagged term as well, since we don't implement a separate lag prior.
            _sigma_map = dict(zip(control_list, prior_sigmas_base))
            prior_sigmas = np.array(
                [_sigma_map[c] for c in control_list] + [_sigma_map[c] for c in control_list]
            )
            _base_df = structural_prior_df_base.copy()
            _base_df.insert(0, "Feature", _base_df["Control Region"])
            _base_df.insert(2, "Term Type", _same_period_label(frequency_config))
            _lag_df = structural_prior_df_base.copy()
            _lag_df["Feature"] = _lag_df["Control Region"].apply(lambda c: f"{c}_lag{lag_periods}")
            _lag_df.insert(2, "Term Type", _lag_term_label(lag_periods, frequency_config))
            _cols = [
                "Feature",
                "Control Region",
                "Term Type",
                "Structural Distance",
                "Structural Similarity",
                "Prior Sigma",
                "Prior Type",
            ]
            structural_prior_df = pd.concat([_base_df[_cols], _lag_df[_cols]], ignore_index=True)
        else:
            prior_sigmas = prior_sigmas_base
            structural_prior_df = structural_prior_df_base
        return PriorSpec(
            prior_sigmas=prior_sigmas,
            structural_prior_df=structural_prior_df,
            prior_style="Structurally informed",
            min_sigma=min_sigma,
            max_sigma=max_sigma,
        )

    prior_sigmas = np.repeat(_STANDARD_SIGMA, len(model_feature_cols))
    if include_lagged_controls:
        structural_prior_df = _standard_prior_rows(
            control_list, model_feature_cols, lag_periods, frequency_config
        )
    else:
        structural_prior_df = pd.DataFrame(
            {
                "Control Region": control_list,
                "Structural Distance": np.nan,
                "Structural Similarity": np.nan,
                "Prior Sigma": prior_sigmas,
                "Prior Type": "Standard weak prior",
            }
        )
    return PriorSpec(
        prior_sigmas=prior_sigmas,
        structural_prior_df=structural_prior_df,
        prior_style="Standard weak prior",
        min_sigma=_DEFAULT_MIN_SIGMA,
        max_sigma=_DEFAULT_MAX_SIGMA,
    )
