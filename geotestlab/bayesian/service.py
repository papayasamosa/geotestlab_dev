"""Bayesian TBR orchestration service (pure; no Streamlit imports).

``run_bayesian`` builds the model data, priors, samples (or uses an injected
sampler for tests), computes fitted-mean / predictive intervals and uplift
aggregation, and returns a typed :class:`BayesianResult` with structured
``warnings`` / ``errors`` / ``blockers`` and the PyMC trace kept separate from
the serialisable summary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.bayesian.ar1 import ar1_gap_steps
from geotestlab.bayesian.exceptions import InsufficientPrePeriodError, MissingTestPeriodError
from geotestlab.bayesian.features import build_bayesian_model_data
from geotestlab.bayesian.model import (
    build_bayesian_model,
    count_divergences,
    extract_posterior,
    sample_bayesian_model,
)
from geotestlab.bayesian.models import BayesianConfig, BayesianResult
from geotestlab.bayesian.predict import (
    compute_fitted_mean_intervals,
    compute_predictive_interval,
    compute_uplift_aggregation,
)
from geotestlab.bayesian.priors import build_prior_spec
from geotestlab.validation import compute_metrics, dates_are_contiguous, get_frequency_config

_ROW_LOSS_MESSAGES = {
    "error": (
        "{} of {} rows ({:.1f}%) were removed because the test series or at least one "
        "selected control had missing KPI values. This is a large share of the data and "
        "the Bayesian TBR result may be unreliable. Controls with missing values: {}."
    ),
    "warning": (
        "{} of {} rows ({:.1f}%) were removed because the test series or at least one "
        "selected control had missing KPI values. This can affect Bayesian TBR "
        "reliability. Controls with missing values: {}."
    ),
}

_AR1_BLOCKER = (
    "Bayesian TBR's AR(1) noise-streak model assumes the pre-period has no calendar "
    "gaps (e.g. from an excluded tracking-outage date) — a gap would be silently "
    "treated as one adjacent period. Either repair/reupload the data so the "
    "pre-period is contiguous, or turn off 'Allow for noise streaks — AR(1) errors' "
    "above and re-run."
)


def run_bayesian(
    model_agg_df,
    structural_agg_df,
    config: BayesianConfig,
    selected_metric,
    model_builder_fn=None,
    sampler_fn=None,
) -> BayesianResult:
    """Run Bayesian TBR and return a typed result.

    ``model_agg_df`` is the validation aggregated dataframe used to build the
    model matrix; ``structural_agg_df`` is the matching aggregated dataframe
    (with structural feature columns) used only for structurally informed
    priors.

    ``model_builder_fn`` / ``sampler_fn`` are test injection points; when either
    is provided the real PyMC import is skipped (fast tests never sample).
    """
    warnings: list[str] = []
    errors: list[str] = []
    blockers: list[str] = []

    freq_config = config.frequency_config or get_frequency_config(config.time_series_frequency)

    # ---- Period timestamps ----
    pre_start_ts = pd.Timestamp(config.pre_start)
    pre_end_ts = pd.Timestamp(config.pre_end)
    test_start_ts = pd.Timestamp(config.test_start) if config.test_start is not None else None
    test_end_ts = pd.Timestamp(config.test_end) if config.test_end is not None else None
    post_start_ts = (
        pd.Timestamp(config.post_start)
        if config.use_post and config.post_start is not None
        else None
    )
    post_end_ts = (
        pd.Timestamp(config.post_end) if config.use_post and config.post_end is not None else None
    )

    # ---- Model data (matrix + lags + splits) ----
    try:
        data = build_bayesian_model_data(
            model_agg_df,
            list(config.control_list),
            list(config.test_regions),
            freq_config,
            config.include_lagged_controls,
            config.lag_periods,
            pre_start_ts,
            pre_end_ts,
            test_start_ts,
            test_end_ts,
            config.use_post,
            post_start_ts,
            post_end_ts,
            min_pre_period_rows=config.min_pre_period_rows,
        )
    except InsufficientPrePeriodError as exc:
        return BayesianResult(completed=False, errors=(str(exc),))
    except MissingTestPeriodError as exc:
        return BayesianResult(completed=False, errors=(str(exc),))

    # ---- Row-loss messages (non-stopping) ----
    md = data.matrix_diagnostics
    _dropped = int(getattr(md, "rows_dropped", 0) or 0)
    _before = int(getattr(md, "rows_before_dropna", 0) or 0)
    _pct = float(getattr(md, "pct_rows_dropped", 0.0) or 0.0)
    _cols_missing = ", ".join(getattr(md, "control_columns_with_missing", ()) or ()) or "none"
    if _dropped > 0 and _pct > 20:
        errors.append(_ROW_LOSS_MESSAGES["error"].format(_dropped, _before, _pct, _cols_missing))
    elif _dropped > 0 and _pct > 10:
        warnings.append(
            _ROW_LOSS_MESSAGES["warning"].format(_dropped, _before, _pct, _cols_missing)
        )

    # ---- AR(1) contiguity guard ----
    if config.use_ar1_errors and not dates_are_contiguous(data.pre_dates, freq_config):
        blockers.append(_AR1_BLOCKER)
        return BayesianResult(
            completed=False,
            warnings=tuple(warnings),
            errors=tuple(errors),
            blockers=tuple(blockers),
        )

    # ---- Priors ----
    prior_spec = build_prior_spec(
        list(config.control_list),
        list(data.feature_cols),
        list(config.feature_cols),
        config.include_lagged_controls,
        config.lag_periods,
        freq_config,
        config.use_structural_priors,
        structural_agg_df,
        list(config.test_regions),
        config.geo_col,
        weight_dict=config.weight_dict,
        population_col=config.population_col,
        X_pre=data.X_pre,
        y_pre=data.y_pre,
    )

    # ---- Lazy PyMC import (only needed on the real sampling path) ----
    if model_builder_fn is None or sampler_fn is None:
        try:
            import arviz as az  # noqa: F401
            import pymc as pm  # noqa: F401
            import pytensor  # noqa: F401
        except ImportError as exc:
            blockers.append(f"**PyMC could not be imported:** {exc}")
            return BayesianResult(
                completed=False,
                warnings=tuple(warnings),
                errors=tuple(errors),
                blockers=tuple(blockers),
            )

    # ---- Build + sample ----
    _builder = model_builder_fn or build_bayesian_model
    _sampler = sampler_fn or sample_bayesian_model
    bmodel = _builder(data.X_pre, data.y_pre_scaled, prior_spec.prior_sigmas, config.use_ar1_errors)
    trace = _sampler(
        bmodel,
        draws=config.mcmc_draws,
        tune=config.mcmc_tune,
        chains=config.mcmc_chains,
        target_accept=config.mcmc_target_accept,
        random_seed=config.mcmc_random_seed,
    )
    n_divergences = count_divergences(trace)
    draws = extract_posterior(trace, data.X_pre.shape[1], config.use_ar1_errors)

    # ---- Fitted-mean intervals ----
    (
        mu_pre_scaled,
        _,
        y_pred_pre_mean,
        pre_lower_mean_hdi,
        pre_upper_mean_hdi,
    ) = compute_fitted_mean_intervals(draws.post_int, draws.post_coeff, data.X_pre, data.scaler_y)
    mu_test_scaled, mu_test_original, y_pred_test_mean, _, _ = compute_fitted_mean_intervals(
        draws.post_int, draws.post_coeff, data.X_test, data.scaler_y
    )

    # ---- Posterior predictive intervals (AR(1) residual paths, seeded) ----
    _pred_rng = np.random.default_rng(config.mcmc_random_seed)
    _e_last_pre = data.y_pre_scaled[-1] - mu_pre_scaled[:, -1]
    _gap_steps_test = ar1_gap_steps(data.pre_dates[-1], data.test_dates[0], freq_config)
    test_lower_pi, test_upper_pi, y_pred_test_predictive_original, resid_test = (
        compute_predictive_interval(
            draws.post_rho,
            draws.post_sigma,
            mu_test_scaled,
            data.scaler_y,
            _pred_rng,
            e_start=_e_last_pre,
            n_gap_steps=_gap_steps_test,
        )
    )

    if data.X_post is not None:
        (
            mu_post_scaled,
            _,
            y_pred_post_mean,
            _,
            _,
        ) = compute_fitted_mean_intervals(
            draws.post_int, draws.post_coeff, data.X_post, data.scaler_y
        )
        _gap_steps_post = ar1_gap_steps(data.test_dates[-1], data.post_dates[0], freq_config)
        post_lower_pi, post_upper_pi, _, _ = compute_predictive_interval(
            draws.post_rho,
            draws.post_sigma,
            mu_post_scaled,
            data.scaler_y,
            _pred_rng,
            e_start=resid_test[:, -1],
            n_gap_steps=_gap_steps_post,
        )
    else:
        y_pred_post_mean = None
        post_lower_pi = None
        post_upper_pi = None

    # ---- Uplift intervals ----
    uplift = compute_uplift_aggregation(
        data.y_test_actual,
        y_pred_test_predictive_original.sum(axis=1),
        mu_test_original,
    )

    # ---- Pre-period fit metrics ----
    corr_b, r2_b, smape_b, rmse_b = compute_metrics(data.y_pre, y_pred_pre_mean)

    # ---- Enrich structural prior df with posterior coefficients ----
    posterior_coeff_means = draws.post_coeff.mean(axis=0)
    structural_prior_df = prior_spec.structural_prior_df.copy()
    structural_prior_df["Posterior Coefficient Mean"] = np.round(posterior_coeff_means, 3)
    structural_prior_df["Posterior Coefficient 3%"] = np.round(
        np.percentile(draws.post_coeff, 3, axis=0), 3
    )
    structural_prior_df["Posterior Coefficient 97%"] = np.round(
        np.percentile(draws.post_coeff, 97, axis=0), 3
    )

    _use_ar1 = config.use_ar1_errors
    return BayesianResult(
        completed=True,
        warnings=tuple(warnings),
        errors=tuple(errors),
        blockers=tuple(blockers),
        pre_dates=data.pre_dates,
        y_pre=data.y_pre,
        y_pred_pre_mean=y_pred_pre_mean,
        pre_lower_mean_hdi=pre_lower_mean_hdi,
        pre_upper_mean_hdi=pre_upper_mean_hdi,
        test_dates=data.test_dates,
        y_test_actual=data.y_test_actual,
        y_pred_test_mean=y_pred_test_mean,
        test_lower_pi=test_lower_pi,
        test_upper_pi=test_upper_pi,
        post_dates=data.post_dates,
        y_post_actual=data.y_post_actual,
        y_pred_post_mean=y_pred_post_mean,
        post_lower_pi=post_lower_pi,
        post_upper_pi=post_upper_pi,
        uplift_samples=uplift["uplift_samples"],
        uplift_pi_lower=uplift["uplift_pi_lower"],
        uplift_pi_upper=uplift["uplift_pi_upper"],
        uplift_hdi_lower=uplift["uplift_hdi_lower"],
        uplift_hdi_upper=uplift["uplift_hdi_upper"],
        prob_pos=uplift["prob_pos"],
        mean_uplift=uplift["mean_uplift"],
        uplift_pct=uplift["uplift_pct"],
        corr=corr_b,
        r2=r2_b,
        smape=smape_b,
        rmse=rmse_b,
        n_divergences=n_divergences,
        n_chains=config.mcmc_chains,
        n_draws=config.mcmc_draws,
        n_tune=config.mcmc_tune,
        target_accept=config.mcmc_target_accept,
        use_ar1_errors=_use_ar1,
        rho_mean=float(np.mean(draws.post_rho)) if _use_ar1 else None,
        rho_hdi_lower=float(np.percentile(draws.post_rho, 3)) if _use_ar1 else None,
        rho_hdi_upper=float(np.percentile(draws.post_rho, 97)) if _use_ar1 else None,
        selected_metric=selected_metric,
        test_start_ts=test_start_ts,
        test_end_ts=test_end_ts,
        prior_style=prior_spec.prior_style,
        prior_sigmas=prior_spec.prior_sigmas,
        structural_prior_df=structural_prior_df,
        min_prior_sigma=prior_spec.min_sigma,
        max_prior_sigma=prior_spec.max_sigma,
        control_list=tuple(config.control_list),
        base_control_list=tuple(config.control_list),
        include_lagged_controls=config.include_lagged_controls,
        model_feature_cols=data.feature_cols,
        lagged_feature_map=data.lagged_feature_map,
        time_series_frequency=config.time_series_frequency,
        frequency_config=freq_config,
        lag_periods=config.lag_periods,
        lag_label=freq_config["lag_label"],
        lag_drop_metadata=data.lag_drop_metadata,
        lag_drop_pct=data.lag_drop_metadata["lag_drop_pct"] if data.lag_drop_metadata else None,
        rows_dropped_due_to_lag=data.lag_drop_metadata["rows_dropped_due_to_lag"]
        if data.lag_drop_metadata
        else None,
        trace=trace,
    )
