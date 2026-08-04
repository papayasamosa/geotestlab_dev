"""Typed configuration, intermediate data, and result objects for the Bayesian core.

The PyMC trace is deliberately kept separate from the serialisable result
summary: ``BayesianResult.trace`` is the only non-serialisable attribute and is
excluded from ``to_dict()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BayesianConfig:
    """Scalar settings for one Bayesian TBR run."""

    method_name: str
    control_list: tuple[str, ...]
    test_regions: tuple[str, ...]
    geo_col: str
    # Structural features (active matching features) used only when
    # structurally informed priors are enabled.
    feature_cols: tuple[str, ...]
    weight_dict: Mapping[str, float] | None = None
    population_col: str = "Population"
    time_series_frequency: str = "weekly"
    # FrequencyConfig (validation package) or a dict-like object.
    frequency_config: Any | None = None
    include_lagged_controls: bool = False
    lag_periods: int = 1
    use_structural_priors: bool = False
    use_ar1_errors: bool = True
    pre_start: Any = None
    pre_end: Any = None
    test_start: Any = None
    test_end: Any = None
    use_post: bool = False
    post_start: Any = None
    post_end: Any = None
    min_pre_period_rows: int = 6
    mcmc_draws: int = 2000
    mcmc_tune: int = 1000
    mcmc_chains: int = 4
    mcmc_target_accept: float = 0.95
    mcmc_random_seed: int = 42


@dataclass
class BayesianModelData:
    """Combined model matrix, period splits, and fitted scalers (intermediate).

    The fitted scalers are intentionally excluded from any serialisable summary;
    they only exist during the computation.
    """

    model_full_bayes: pd.DataFrame
    feature_cols: tuple[str, ...]
    lagged_feature_map: dict
    lag_drop_metadata: dict | None
    matrix_diagnostics: Any
    # Pre period: X is scaled; y_pre is the ORIGINAL test KPI; y_pre_scaled scaled.
    X_pre: np.ndarray
    y_pre: np.ndarray
    y_pre_scaled: np.ndarray
    pre_dates: np.ndarray
    # Test period: X scaled, y actual original.
    X_test: np.ndarray
    y_test_actual: np.ndarray
    test_dates: np.ndarray
    # Post period (optional): X scaled, y actual original.
    X_post: np.ndarray | None
    y_post_actual: np.ndarray | None
    post_dates: np.ndarray | None
    scaler_X: Any
    scaler_y: Any


@dataclass
class PriorSpec:
    """Coefficient prior sigmas plus the human-readable prior table."""

    prior_sigmas: np.ndarray
    structural_prior_df: pd.DataFrame
    prior_style: str
    min_sigma: float
    max_sigma: float


@dataclass(frozen=True)
class PosteriorDraws:
    """Flattened posterior arrays extracted from a PyMC trace."""

    post_int: np.ndarray
    post_coeff: np.ndarray
    post_sigma: np.ndarray
    post_rho: np.ndarray


@dataclass
class BayesianResult:
    """Typed result of one Bayesian TBR run.

    ``warnings`` / ``errors`` / ``blockers`` follow the validation-core
    convention (rendered with ``st.warning`` / ``st.error`` /
    ``st.error`` + ``st.stop`` by the Streamlit adapter). ``completed`` is False
    when the model could not be built or sampled.

    ``trace`` holds the PyMC trace and is the ONLY non-serialisable attribute;
    it is excluded from :meth:`to_dict`.
    """

    completed: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    # ---- Serialisable result fields (populated when completed) ----
    pre_dates: Any = None
    y_pre: Any = None
    y_pred_pre_mean: Any = None
    pre_lower_mean_hdi: Any = None
    pre_upper_mean_hdi: Any = None
    test_dates: Any = None
    y_test_actual: Any = None
    y_pred_test_mean: Any = None
    test_lower_pi: Any = None
    test_upper_pi: Any = None
    post_dates: Any = None
    y_post_actual: Any = None
    y_pred_post_mean: Any = None
    post_lower_pi: Any = None
    post_upper_pi: Any = None
    uplift_samples: Any = None
    uplift_pi_lower: Any = None
    uplift_pi_upper: Any = None
    uplift_hdi_lower: Any = None
    uplift_hdi_upper: Any = None
    prob_pos: Any = None
    mean_uplift: Any = None
    uplift_pct: Any = None
    corr: Any = None
    r2: Any = None
    smape: Any = None
    rmse: Any = None
    n_divergences: Any = None
    n_chains: Any = None
    n_draws: Any = None
    n_tune: Any = None
    target_accept: Any = None
    use_ar1_errors: bool = False
    rho_mean: Any = None
    rho_hdi_lower: Any = None
    rho_hdi_upper: Any = None
    selected_metric: Any = None
    test_start_ts: Any = None
    test_end_ts: Any = None
    prior_style: Any = None
    prior_sigmas: Any = None
    structural_prior_df: Any = None
    min_prior_sigma: Any = None
    max_prior_sigma: Any = None
    control_list: tuple[str, ...] = ()
    base_control_list: tuple[str, ...] = ()
    include_lagged_controls: bool = False
    model_feature_cols: Any = None
    lagged_feature_map: Any = None
    time_series_frequency: str = "weekly"
    frequency_config: Any = None
    lag_periods: Any = None
    lag_label: Any = None
    lag_drop_metadata: Any = None
    lag_drop_pct: Any = None
    rows_dropped_due_to_lag: Any = None

    # ---- Non-serialisable ----
    trace: Any = None

    def to_dict(self) -> dict:
        """Legacy serialisable result dict for the Streamlit UI (trace excluded)."""
        return {
            "pre_dates": self.pre_dates,
            "y_pre": self.y_pre,
            "y_pred_pre_mean": self.y_pred_pre_mean,
            "pre_lower_mean_hdi": self.pre_lower_mean_hdi,
            "pre_upper_mean_hdi": self.pre_upper_mean_hdi,
            "test_dates": self.test_dates,
            "y_test_actual": self.y_test_actual,
            "y_pred_test_mean": self.y_pred_test_mean,
            "test_lower_pi": self.test_lower_pi,
            "test_upper_pi": self.test_upper_pi,
            "post_dates": self.post_dates,
            "y_post_actual": self.y_post_actual,
            "y_pred_post_mean": self.y_pred_post_mean,
            "post_lower_pi": self.post_lower_pi,
            "post_upper_pi": self.post_upper_pi,
            "uplift_samples": self.uplift_samples,
            "uplift_pi_lower": self.uplift_pi_lower,
            "uplift_pi_upper": self.uplift_pi_upper,
            "uplift_hdi_lower": self.uplift_hdi_lower,
            "uplift_hdi_upper": self.uplift_hdi_upper,
            "prob_pos": self.prob_pos,
            "mean_uplift": self.mean_uplift,
            "uplift_pct": self.uplift_pct,
            "corr": self.corr,
            "r2": self.r2,
            "smape": self.smape,
            "rmse": self.rmse,
            "n_divergences": self.n_divergences,
            "n_chains": self.n_chains,
            "n_draws": self.n_draws,
            "n_tune": self.n_tune,
            "target_accept": self.target_accept,
            "use_ar1_errors": self.use_ar1_errors,
            "rho_mean": self.rho_mean,
            "rho_hdi_lower": self.rho_hdi_lower,
            "rho_hdi_upper": self.rho_hdi_upper,
            "selected_metric": self.selected_metric,
            "test_start_ts": self.test_start_ts,
            "test_end_ts": self.test_end_ts,
            "prior_style": self.prior_style,
            "prior_sigmas": self.prior_sigmas,
            "structural_prior_df": self.structural_prior_df,
            "min_prior_sigma": self.min_prior_sigma,
            "max_prior_sigma": self.max_prior_sigma,
            "control_list": list(self.control_list),
            "base_control_list": list(self.base_control_list),
            "include_lagged_controls": self.include_lagged_controls,
            "model_feature_cols": list(self.model_feature_cols)
            if self.model_feature_cols is not None
            else None,
            "lagged_feature_map": self.lagged_feature_map,
            "time_series_frequency": self.time_series_frequency,
            "frequency_config": self.frequency_config,
            "lag_periods": self.lag_periods,
            "lag_label": self.lag_label,
            "lag_drop_metadata": self.lag_drop_metadata,
            "lag_drop_pct": self.lag_drop_pct,
            "rows_dropped_due_to_lag": self.rows_dropped_due_to_lag,
        }
