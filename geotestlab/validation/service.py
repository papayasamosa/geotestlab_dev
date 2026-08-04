"""Validation orchestration: the pure service.

Runs one validation method (ElasticNet or LASSO) over an aggregated KPI frame and
returns a typed :class:`~geotestlab.validation.models.ValidationResult` with the
pre-period fit, rolling-origin validation, placebo analysis, Counterfactual
Confidence, and the serialisable legacy summary consumed by the Streamlit UI.

No Streamlit imports. Structured diagnostics are returned on the result:
``warnings`` (render with ``st.warning``), ``errors`` (render with ``st.error``,
non-stopping), ``blockers`` (render with ``st.error`` plus ``st.stop``), and
``insufficient_pre_period`` (the legacy adapter returns ``None``).
"""

from __future__ import annotations

import re
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from geotestlab.validation.confidence import (
    calculate_overfit_gap,
    classify_autocorrelation_risk,
    classify_overfitting_risk,
    classify_rolling_bias_risk,
    classify_rolling_validation_error,
    combine_reliability_ratings,
    get_reliability_drivers,
)
from geotestlab.validation.matrix import (
    add_lagged_control_features,
    build_model_matrix,
)
from geotestlab.validation.metrics import (
    compute_metrics,
    durbin_watson_stat,
)
from geotestlab.validation.models import (
    CounterfactualConfidence,
    ModelMatrixDiagnostics,
    PlaceboDiagnostics,
    RegularisationDiagnostics,
    RollingOriginDiagnostics,
    ValidationConfig,
    ValidationPeriods,
    ValidationResult,
)
from geotestlab.validation.placebo import (
    run_placebo_windows,
    summarize_placebo_results,
)
from geotestlab.validation.regularisation import (
    build_regularized_model,
    classify_validation_method,
)
from geotestlab.validation.rolling_origin import (
    rolling_origin_validation,
    summarize_rolling_origin_folds,
)


def _row_loss_messages(
    diagnostics: ModelMatrixDiagnostics,
) -> tuple[list[str], list[str]]:
    """Build the (errors, warnings) row-loss messages from matrix diagnostics.

    Mirrors the previous inline behaviour: >20% rows dropped is styled as an error
    (non-stopping), >10% as a warning; otherwise no message.
    """
    errors: list[str] = []
    warnings: list[str] = []
    pct_dropped = diagnostics.pct_rows_dropped
    rows_dropped = diagnostics.rows_dropped
    rows_before = diagnostics.rows_before_dropna
    controls_missing = ", ".join(diagnostics.control_columns_with_missing) or "none"
    if rows_dropped > 0 and pct_dropped > 20:
        errors.append(
            f"{rows_dropped} of {rows_before} rows ({pct_dropped:.1f}%) were removed because "
            "the test series or at least one selected control had missing KPI values. "
            "This is a large share of the data and the validation result may be unreliable. "
            f"Controls with missing values: {controls_missing}."
        )
    elif rows_dropped > 0 and pct_dropped > 10:
        warnings.append(
            f"{rows_dropped} of {rows_before} rows ({pct_dropped:.1f}%) were removed because "
            "the test series or at least one selected control had missing KPI values. "
            "This can affect validation reliability. "
            f"Controls with missing values: {controls_missing}."
        )
    return errors, warnings


def _cv_fallback_messages(
    method_name: str,
    main_model_used_cv_fallback: bool,
    fold_df: pd.DataFrame,
) -> list[str]:
    """Build the TimeSeriesSplit-fallback warning messages (one per triggered case)."""
    warnings: list[str] = []
    if main_model_used_cv_fallback:
        warnings.append(
            f"⚠️ There is insufficient pre-period history to run leakage-free TimeSeriesSplit "
            f"cross-validation for **{method_name}**. This method has not been given a "
            "confidence rating. Add more pre-period data or reduce the validation window."
        )
    elif not fold_df.empty and bool(fold_df["used_cv_fallback"].any()):
        n_fallback_folds = int(fold_df["used_cv_fallback"].sum())
        warnings.append(
            f"⚠️ {n_fallback_folds} of {len(fold_df)} rolling-origin folds for **{method_name}** "
            "did not have enough training history for leakage-free TimeSeriesSplit cross-validation. "
            "Those folds were fit exploratorily with a fixed regularisation strength and are excluded "
            "from the rolling-origin validation metrics and Counterfactual Confidence shown here."
        )
    return warnings


def run_validation(
    agg_df,
    control_list,
    test_regions,
    config: ValidationConfig,
    periods: ValidationPeriods,
    rolling_origin_fn: Callable | None = None,
) -> ValidationResult:
    """Run a single validation method and return a typed result.

    ``rolling_origin_fn`` allows the Streamlit adapter to inject an
    ``st.cache_data``-wrapped rolling-origin callable so caching behaviour is
    preserved; defaults to the plain package function.
    """
    frequency_config = config.frequency_config
    lag_periods = frequency_config["lag_periods"]
    method_name = config.method_name
    compute_uplift = config.compute_uplift
    placebo_length_periods = config.placebo_length_periods
    min_training_periods = config.min_training_periods
    include_lagged_controls = config.include_lagged_controls

    pre_start = periods.pre_start
    pre_end = periods.pre_end
    test_start = periods.test_start
    test_end = periods.test_end
    use_post = periods.use_post
    post_start = periods.post_start
    post_end = periods.post_end

    warnings: list[str] = []
    errors: list[str] = []

    # ---- Build a combined pre + test/post model matrix so lagged features apply
    # once, across the full continuous date range, before splitting back out. ----
    combined_end_candidates = [pre_end]
    if test_end is not None:
        combined_end_candidates.append(test_end)
    if use_post and post_end is not None:
        combined_end_candidates.append(post_end)
    combined_end = max(combined_end_candidates)

    full_mask = (agg_df["date"] >= pre_start) & (agg_df["date"] <= combined_end)
    model_full, matrix_diagnostics = build_model_matrix(
        agg_df[full_mask], control_list, test_regions
    )

    # ---- Row-loss diagnostics (structured messages; adapter renders them). ----
    row_errors, row_warnings = _row_loss_messages(matrix_diagnostics)
    errors.extend(row_errors)
    warnings.extend(row_warnings)

    if include_lagged_controls:
        model_full, model_feature_cols, lagged_feature_map, lag_drop_metadata = (
            add_lagged_control_features(
                model_full, control_list, lags=(lag_periods,), frequency_config=frequency_config
            )
        )
    else:
        model_feature_cols = list(control_list)
        lagged_feature_map = {}
        lag_drop_metadata = None

    # ---- Defensive check: control regions with no matching data at all. ----
    _missing_feature_cols = [c for c in model_feature_cols if c not in model_full.columns]
    if _missing_feature_cols:
        blocker = (
            "Could not build the validation model — the following control region(s) have no "
            "matching data in the uploaded KPI file: "
            + ", ".join(map(str, _missing_feature_cols))
            + ". This usually means the aggregation level or region names in this file don't match "
            "the ones used in Region Matching."
        )
        return _failure(frequency_config, warnings, errors, blockers=(blocker,))

    # Pre-period data (sliced from the combined, already-lagged matrix)
    pre_mask = (model_full["date"] >= pre_start) & (model_full["date"] <= pre_end)
    model_pre = model_full[pre_mask].sort_values("date").reset_index(drop=True)
    if len(model_pre) < 6:
        return _failure(
            frequency_config,
            warnings,
            errors,
            insufficient_pre_period=True,
        )
    X_pre = model_pre[model_feature_cols].values
    y_pre = model_pre["test_kpi"].values
    dates_pre = model_pre["date"].tolist()
    scaler = StandardScaler()
    X_pre_scaled = scaler.fit_transform(X_pre)

    model, main_model_cv_status, main_model_used_cv = build_regularized_model(
        method_name, len(y_pre), n_splits_pref=5
    )
    main_model_used_cv_fallback = not main_model_used_cv
    model.fit(X_pre_scaled, y_pre)
    y_pred_pre = model.predict(X_pre_scaled)
    corr, r2, s, rmse = compute_metrics(y_pre, y_pred_pre)

    pre_residuals = y_pre - y_pred_pre
    dw_stat = durbin_watson_stat(pre_residuals)

    cv_horizon = (
        placebo_length_periods
        if placebo_length_periods is not None
        else frequency_config["default_validation_horizon_periods"]
    )
    _rolling_origin = (
        rolling_origin_fn if rolling_origin_fn is not None else rolling_origin_validation
    )
    (
        fold_df,
        rolling_smape_mean,
        rolling_rmse_mean,
        rolling_cv_status,
        rolling_windows_skipped_non_contiguous,
    ) = _rolling_origin(
        X_pre,
        y_pre,
        frequency_config,
        horizon=cv_horizon,
        min_training_periods=min_training_periods,
        dates=dates_pre,
        model_type=method_name,
    )
    holdout_smape_mean = rolling_smape_mean
    holdout_rmse_mean = rolling_rmse_mean

    cv_status = f"Main model: {main_model_cv_status} Rolling-origin folds: {rolling_cv_status}"
    warnings.extend(_cv_fallback_messages(method_name, main_model_used_cv_fallback, fold_df))

    _rolling_summary = summarize_rolling_origin_folds(fold_df)
    rolling_smape_p90 = _rolling_summary["rolling_smape_p90"]
    rolling_bias_pct_mean = _rolling_summary["rolling_bias_pct_mean"]
    rolling_uplift_error_pct_median = _rolling_summary["rolling_uplift_error_pct_median"]
    rolling_uplift_error_pct_lower = _rolling_summary["rolling_uplift_error_pct_lower"]
    rolling_uplift_error_pct_upper = _rolling_summary["rolling_uplift_error_pct_upper"]

    n_pre_periods = len(y_pre)
    overfit_gap_smape = calculate_overfit_gap(s, rolling_smape_mean)
    overfit_gap_rmse = calculate_overfit_gap(rmse, rolling_rmse_mean)

    # Test period predictions (if uplift required)
    model_test = None
    if compute_uplift and test_start is not None and test_end is not None:
        test_mask = (model_full["date"] >= test_start) & (model_full["date"] <= test_end)
        model_test = model_full[test_mask].sort_values("date").reset_index(drop=True)
        if not model_test.empty:
            X_test = model_test[model_feature_cols].values
            X_test_scaled = scaler.transform(X_test)
            y_test_actual = model_test["test_kpi"].values
            y_pred_test = model.predict(X_test_scaled)
            uplift = y_test_actual.sum() - y_pred_test.sum()
            uplift_pct = (uplift / y_pred_test.sum()) * 100 if y_pred_test.sum() != 0 else np.nan
            dates_test = model_test["date"].tolist()
        else:
            uplift = uplift_pct = None
            y_test_actual = y_pred_test = None
            dates_test = []
    else:
        uplift = uplift_pct = None
        y_test_actual = y_pred_test = None
        dates_test = []

    # Post-period (if any)
    if use_post and post_start is not None and post_end is not None:
        post_mask = (model_full["date"] >= post_start) & (model_full["date"] <= post_end)
        model_post = model_full[post_mask].sort_values("date").reset_index(drop=True)
        if not model_post.empty:
            X_post = model_post[model_feature_cols].values
            X_post_scaled = scaler.transform(X_post)
            y_post_pred = model.predict(X_post_scaled)
            y_post_actual = model_post["test_kpi"].values
            dates_post = model_post["date"].tolist()
        else:
            y_post_pred = y_post_actual = dates_post = None
    else:
        y_post_pred = y_post_actual = dates_post = None

    neg_pre = any(y_pred_pre < 0)
    neg_test = any(y_pred_test < 0) if y_pred_test is not None else False
    neg_post = any(y_post_pred < 0) if y_post_pred is not None else False

    # ---------- Placebo generation (using the same model type) ----------
    if compute_uplift:
        if placebo_length_periods is not None:
            placebo_len = placebo_length_periods
        elif model_test is not None and not model_test.empty:
            placebo_len = len(model_test)
        elif test_start is not None and test_end is not None:
            if frequency_config["frequency"] == "daily":
                placebo_len = max(1, (test_end - test_start).days + 1)
            else:
                placebo_len = max(1, (test_end - test_start).days // 7 + 1)
        else:
            placebo_len = None
    else:
        placebo_len = None

    placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, placebo_window_diagnostics = (
        run_placebo_windows(
            model_pre,
            model_feature_cols,
            dates_pre,
            min_training_periods,
            placebo_len,
            method_name,
            frequency_config,
        )
    )

    _placebo_summary = summarize_placebo_results(
        placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, uplift
    )
    median_uplift = _placebo_summary["median_uplift"]
    p2_5 = _placebo_summary["p2_5"]
    p97_5 = _placebo_summary["p97_5"]
    median_placebo_smape = _placebo_summary["median_placebo_smape"]
    p95_placebo_smape = _placebo_summary["p95_placebo_smape"]
    median_placebo_rmse = _placebo_summary["median_placebo_rmse"]
    p95_placebo_rmse = _placebo_summary["p95_placebo_rmse"]
    median_placebo_uplift_pct = _placebo_summary["median_placebo_uplift_pct"]
    p2_5_pct = _placebo_summary["p2_5_pct"]
    p97_5_pct = _placebo_summary["p97_5_pct"]
    percentile_rank = _placebo_summary["percentile_rank"]
    p_one_sided = _placebo_summary["p_one_sided"]
    p_two_sided = _placebo_summary["p_two_sided"]
    z_score = _placebo_summary["z_score"]

    coefs = model.coef_
    coeff_threshold = 1e-6
    coeff_dict = dict(zip(model_feature_cols, coefs))
    same_period_label = "Same day" if frequency_config["frequency"] == "daily" else "Same week"

    def _feature_to_region_and_term(feat):
        for c in control_list:
            if feat == c:
                return c, same_period_label
            lag_match = re.match(rf"^{re.escape(c)}_lag(\d+)$", feat)
            if lag_match:
                lag_n = int(lag_match.group(1))
                period_word = "day" if frequency_config["frequency"] == "daily" else "week"
                period_word_plural = period_word + "s" if lag_n != 1 else period_word
                return c, f"Lag {lag_n} {period_word_plural}"
        return feat, same_period_label

    selected_df_rows = []
    for feat in model_feature_cols:
        base_region, term_type = _feature_to_region_and_term(feat)
        coeff_val = float(coeff_dict[feat])
        selected_df_rows.append(
            {
                "Feature": feat,
                "Base Region": base_region,
                "Term Type": term_type,
                "Coefficient": round(coeff_val, 4),
                "Non-zero Coefficient": abs(coeff_val) > coeff_threshold,
            }
        )
    selected_df = pd.DataFrame(
        selected_df_rows,
        columns=["Feature", "Base Region", "Term Type", "Coefficient", "Non-zero Coefficient"],
    )

    selected_features = [row["Feature"] for row in selected_df_rows if row["Non-zero Coefficient"]]
    selected = sorted(
        {row["Base Region"] for row in selected_df_rows if row["Non-zero Coefficient"]},
        key=lambda r: control_list.index(r) if r in control_list else 0,
    )
    n_candidates = len(control_list)
    n_selected = len(selected)
    n_removed = n_candidates - n_selected
    alpha = getattr(model, "alpha_", np.nan)
    n_selected_features = len(selected_features)

    rolling_validation_error_risk = classify_rolling_validation_error(rolling_smape_mean)
    overfitting_risk = classify_overfitting_risk(overfit_gap_smape)
    rolling_bias_risk = classify_rolling_bias_risk(rolling_bias_pct_mean)
    autocorrelation_risk = classify_autocorrelation_risk(dw_stat)
    validation_method_label = classify_validation_method(fold_df, main_model_used_cv_fallback)

    reliability_components = {
        "rolling validation error": rolling_validation_error_risk,
        "overfitting gap": overfitting_risk,
        "autocorrelation risk": autocorrelation_risk,
        "rolling bias": rolling_bias_risk,
    }
    counterfactual_reliability = combine_reliability_ratings(reliability_components)
    reliability_drivers = get_reliability_drivers(reliability_components)

    used_cv_fallback = main_model_used_cv_fallback or (
        not fold_df.empty and bool(fold_df["used_cv_fallback"].any())
    )

    summary = {
        "dates_pre": dates_pre,
        "y_pre": y_pre,
        "y_pred_pre": y_pred_pre,
        "corr": corr,
        "r2": r2,
        "smape": s,
        "rmse": rmse,
        "dw_stat": dw_stat,
        "autocorrelation_risk": autocorrelation_risk,
        "pre_residuals": pre_residuals,
        "holdout_smape_mean": holdout_smape_mean,
        "holdout_rmse_mean": holdout_rmse_mean,
        "rolling_origin_folds": fold_df,
        "rolling_smape_mean": rolling_smape_mean,
        "rolling_windows_skipped_non_contiguous": rolling_windows_skipped_non_contiguous,
        "rolling_rmse_mean": rolling_rmse_mean,
        "rolling_smape_p90": rolling_smape_p90,
        "rolling_bias_pct_mean": rolling_bias_pct_mean,
        "rolling_validation_error_risk": rolling_validation_error_risk,
        "rolling_bias_risk": rolling_bias_risk,
        "rolling_uplift_error_pct_median": rolling_uplift_error_pct_median,
        "rolling_uplift_error_pct_lower": rolling_uplift_error_pct_lower,
        "rolling_uplift_error_pct_upper": rolling_uplift_error_pct_upper,
        "overfit_gap_smape": overfit_gap_smape,
        "overfit_gap_rmse": overfit_gap_rmse,
        "overfitting_risk": overfitting_risk,
        "validation_method_label": validation_method_label,
        "cv_status": cv_status,
        "used_cv_fallback": used_cv_fallback,
        "main_model_used_cv_fallback": main_model_used_cv_fallback,
        "n_selected_features": n_selected_features,
        "n_pre_periods": n_pre_periods,
        "n_pre_weeks": n_pre_periods,
        "counterfactual_reliability": counterfactual_reliability,
        "reliability_drivers": reliability_drivers,
        "min_training_periods": min_training_periods,
        "min_training_weeks": min_training_periods,
        "validation_window_periods": cv_horizon,
        "validation_window_weeks": cv_horizon,
        "time_series_frequency": frequency_config["frequency"],
        "frequency_config": frequency_config,
        "lag_periods": lag_periods,
        "lag_label": frequency_config["lag_label"],
        "lag_drop_metadata": lag_drop_metadata,
        "matrix_diagnostics": matrix_diagnostics.to_dict(),
        "placebo_length_periods": placebo_len,
        "uplift": uplift,
        "uplift_pct": uplift_pct,
        "dates_test": dates_test,
        "y_test_actual": y_test_actual,
        "y_pred_test": y_pred_test,
        "dates_post": dates_post,
        "y_post_actual": y_post_actual,
        "y_post_pred": y_post_pred,
        "placebos": placebos,
        "placebo_uplift_pcts": placebo_uplift_pcts,
        "placebo_smapes": placebo_smapes,
        "placebo_rmses": placebo_rmses,
        "placebo_window_diagnostics": placebo_window_diagnostics,
        "median_placebo_uplift": median_uplift,
        "placebo_range_lower": p2_5,
        "placebo_range_upper": p97_5,
        "median_placebo_uplift_pct": median_placebo_uplift_pct,
        "placebo_range_lower_pct": p2_5_pct,
        "placebo_range_upper_pct": p97_5_pct,
        "placebo_percentile_rank": percentile_rank,
        "placebo_p_value_one_sided": p_one_sided,
        "placebo_p_value_two_sided": p_two_sided,
        "placebo_z_score": z_score,
        "median_placebo_smape": median_placebo_smape,
        "p95_placebo_smape": p95_placebo_smape,
        "median_placebo_rmse": median_placebo_rmse,
        "p95_placebo_rmse": p95_placebo_rmse,
        "neg_pre": neg_pre,
        "neg_test": neg_test,
        "neg_post": neg_post,
        "selected_regions": selected,
        "selected_features": selected_features,
        "selected_df": selected_df,
        "n_candidates": n_candidates,
        "n_selected": n_selected,
        "n_removed": n_removed,
        "alpha": alpha,
        "control_list": list(control_list),
        "base_control_list": list(control_list),
        "include_lagged_controls": include_lagged_controls,
        "model_feature_cols": model_feature_cols,
        "lagged_feature_map": lagged_feature_map,
    }

    rolling_diag = RollingOriginDiagnostics(
        fold_df=fold_df,
        rolling_smape_mean=rolling_smape_mean,
        rolling_rmse_mean=rolling_rmse_mean,
        rolling_smape_p90=rolling_smape_p90,
        rolling_bias_pct_mean=rolling_bias_pct_mean,
        rolling_uplift_error_pct_median=rolling_uplift_error_pct_median,
        rolling_uplift_error_pct_lower=rolling_uplift_error_pct_lower,
        rolling_uplift_error_pct_upper=rolling_uplift_error_pct_upper,
        windows_skipped_non_contiguous=rolling_windows_skipped_non_contiguous,
        cv_status=rolling_cv_status,
    )
    placebo_diag = PlaceboDiagnostics(
        placebos=tuple(placebos),
        placebo_uplift_pcts=tuple(placebo_uplift_pcts),
        placebo_smapes=tuple(placebo_smapes),
        placebo_rmses=tuple(placebo_rmses),
        windows_available=placebo_window_diagnostics.get("windows_available", 0),
        windows_used=placebo_window_diagnostics.get("windows_used", 0),
        windows_skipped_non_contiguous=placebo_window_diagnostics.get(
            "windows_skipped_non_contiguous", 0
        ),
        median_uplift=median_uplift,
        range_lower=p2_5,
        range_upper=p97_5,
        median_uplift_pct=median_placebo_uplift_pct,
        range_lower_pct=p2_5_pct,
        range_upper_pct=p97_5_pct,
        percentile_rank=percentile_rank,
        p_one_sided=p_one_sided,
        p_two_sided=p_two_sided,
        z_score=z_score,
        median_placebo_smape=median_placebo_smape,
        p95_placebo_smape=p95_placebo_smape,
        median_placebo_rmse=median_placebo_rmse,
        p95_placebo_rmse=p95_placebo_rmse,
    )
    confidence_diag = CounterfactualConfidence(
        rating=counterfactual_reliability,
        drivers=reliability_drivers,
        components=dict(reliability_components),
    )
    regularisation_diag = RegularisationDiagnostics(
        cv_status=cv_status,
        used_cv_fallback=used_cv_fallback,
        main_model_used_cv_fallback=main_model_used_cv_fallback,
        validation_method_label=validation_method_label,
        n_selected_features=n_selected_features,
        n_candidates=n_candidates,
        n_selected=n_selected,
        n_removed=n_removed,
        alpha=alpha,
    )

    return ValidationResult(
        ok=True,
        warnings=tuple(warnings),
        errors=tuple(errors),
        blockers=(),
        insufficient_pre_period=False,
        frequency_config=frequency_config,
        matrix_diagnostics=matrix_diagnostics,
        rolling=rolling_diag,
        placebo=placebo_diag,
        confidence=confidence_diag,
        regularisation=regularisation_diag,
        summary=summary,
        model=model,
        scaler=scaler,
    )


def _failure(
    frequency_config,
    warnings: list[str],
    errors: list[str],
    blockers: tuple[str, ...] = (),
    insufficient_pre_period: bool = False,
) -> ValidationResult:
    return ValidationResult(
        ok=False,
        warnings=tuple(warnings),
        errors=tuple(errors),
        blockers=blockers,
        insufficient_pre_period=insufficient_pre_period,
        frequency_config=frequency_config,
    )
