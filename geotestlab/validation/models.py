"""Typed inputs and outputs for the validation core.

Immutable dataclasses. ``ValidationResult`` separates serialisable summaries
from fitted scikit-learn objects: the ``summary`` dict reproduces the legacy
result shape consumed by the Streamlit UI, while the fitted ``model`` and
``scaler`` are kept as separate fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True)
class FrequencyConfig:
    """Frequency-aware validation settings (weekly vs daily).

    Also supports dict-style access (``fc["frequency"]``, ``fc.get("frequency")``)
    so existing callers that treated the config as a plain dict keep working.
    """

    frequency: str
    period_label_singular: str
    period_label_plural: str
    lag_periods: int
    lag_label: str
    default_min_training_periods: int
    default_validation_horizon_periods: int
    default_placebo_length_periods: int

    def __getitem__(self, key: str):
        if key not in self.__dataclass_fields__:
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default=None):
        return getattr(self, key, default) if key in self.__dataclass_fields__ else default

    def keys(self) -> tuple[str, ...]:
        return tuple(self.__dataclass_fields__.keys())


@dataclass(frozen=True)
class ValidationConfig:
    """Scalar settings for one validation method run."""

    method_name: str
    compute_uplift: bool
    placebo_length_periods: int | None
    min_training_periods: int
    include_lagged_controls: bool
    time_series_frequency: str
    frequency_config: FrequencyConfig


@dataclass(frozen=True)
class ValidationPeriods:
    """Pre/test/post date windows for validation."""

    pre_start: pd.Timestamp
    pre_end: pd.Timestamp
    test_start: pd.Timestamp | None
    test_end: pd.Timestamp | None
    use_post: bool
    post_start: pd.Timestamp | None
    post_end: pd.Timestamp | None


@dataclass(frozen=True)
class ModelMatrixDiagnostics:
    """Row-loss diagnostics from model-matrix construction."""

    rows_before_dropna: int
    rows_after_dropna: int
    rows_dropped: int
    pct_rows_dropped: float
    control_columns_with_missing: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "rows_before_dropna": self.rows_before_dropna,
            "rows_after_dropna": self.rows_after_dropna,
            "rows_dropped": self.rows_dropped,
            "pct_rows_dropped": self.pct_rows_dropped,
            "control_columns_with_missing": list(self.control_columns_with_missing),
        }


@dataclass(frozen=True)
class RegularisationDiagnostics:
    """Model-selection diagnostics (TimeSeriesSplit CV vs exploratory fallback)."""

    cv_status: str
    used_cv_fallback: bool
    main_model_used_cv_fallback: bool
    validation_method_label: str
    n_selected_features: int
    n_candidates: int
    n_selected: int
    n_removed: int
    alpha: float


@dataclass(frozen=True)
class RollingOriginDiagnostics:
    """Rolling-origin validation summaries (TimeSeriesSplit-CV folds only)."""

    fold_df: pd.DataFrame
    rolling_smape_mean: float
    rolling_rmse_mean: float
    rolling_smape_p90: float
    rolling_bias_pct_mean: float
    rolling_uplift_error_pct_median: float
    rolling_uplift_error_pct_lower: float
    rolling_uplift_error_pct_upper: float
    windows_skipped_non_contiguous: int
    cv_status: str


@dataclass(frozen=True)
class PlaceboDiagnostics:
    """Placebo-window construction and summary statistics."""

    placebos: tuple[float, ...]
    placebo_uplift_pcts: tuple[float, ...]
    placebo_smapes: tuple[float, ...]
    placebo_rmses: tuple[float, ...]
    windows_available: int
    windows_used: int
    windows_skipped_non_contiguous: int
    median_uplift: float
    range_lower: float
    range_upper: float
    median_uplift_pct: float
    range_lower_pct: float
    range_upper_pct: float
    percentile_rank: float
    p_one_sided: float
    p_two_sided: float
    z_score: float
    median_placebo_smape: float
    p95_placebo_smape: float
    median_placebo_rmse: float
    p95_placebo_rmse: float


@dataclass(frozen=True)
class CounterfactualConfidence:
    """Overall Counterfactual Confidence rating, drivers and component ratings."""

    rating: str
    drivers: str
    components: Mapping[str, str]


@dataclass(frozen=True)
class ValidationResult:
    """Typed result of one validation method run.

    ``warnings`` are rendered with ``st.warning``, ``errors`` with ``st.error``
    (non-stopping), ``blockers`` with ``st.error`` plus ``st.stop``.
    ``insufficient_pre_period`` signals that no model could be built (the legacy
    Streamlit adapter returns ``None`` for that case).

    ``summary`` is the serialisable legacy result dict consumed by the existing
    UI. The fitted scikit-learn ``model`` and ``scaler`` are kept separate.
    """

    ok: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    blockers: tuple[str, ...]
    insufficient_pre_period: bool
    frequency_config: FrequencyConfig
    matrix_diagnostics: ModelMatrixDiagnostics | None = None
    rolling: RollingOriginDiagnostics | None = None
    placebo: PlaceboDiagnostics | None = None
    confidence: CounterfactualConfidence | None = None
    regularisation: RegularisationDiagnostics | None = None
    summary: dict | None = None
    model: Any | None = None
    scaler: Any | None = None

    def to_dict(self) -> dict:
        """Return the legacy serialisable result dict for the Streamlit UI."""
        if self.summary is None:
            raise ValueError("No summary available (validation did not succeed).")
        return self.summary
