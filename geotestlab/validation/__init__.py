"""GeoTestLab validation core: pure, Streamlit-free time-series validation.

Modules:
- ``frequency`` — frequency configuration and inference;
- ``matrix`` — model-matrix construction and calendar-exact lagged controls;
- ``metrics`` — sMAPE, RMSE, correlation, R-squared, Durbin-Watson;
- ``regularisation`` — time-series-safe regularised model selection;
- ``rolling_origin`` — rolling-origin folds and non-contiguous-window handling;
- ``placebo`` — placebo-window construction and summary statistics;
- ``confidence`` — Counterfactual Confidence traffic lights and cascade;
- ``service`` — validation orchestration returning a typed ``ValidationResult``.
"""

from __future__ import annotations

from geotestlab.validation.confidence import (
    RELIABILITY_THRESHOLDS,
    calculate_overfit_gap,
    classify_autocorrelation_risk,
    classify_overfitting_risk,
    classify_rolling_bias_risk,
    classify_rolling_validation_error,
    combine_reliability_ratings,
    get_reliability_drivers,
)
from geotestlab.validation.exceptions import (
    InsufficientPrePeriodError,
    MissingControlColumnsError,
    ValidationError,
)
from geotestlab.validation.frequency import (
    dates_are_contiguous,
    get_frequency_config,
    infer_time_series_frequency,
)
from geotestlab.validation.matrix import (
    add_lagged_control_features,
    build_model_matrix,
)
from geotestlab.validation.metrics import (
    compute_metrics,
    durbin_watson_stat,
    smape,
)
from geotestlab.validation.models import (
    CounterfactualConfidence,
    FrequencyConfig,
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
    safe_tscv,
)
from geotestlab.validation.rolling_origin import (
    rolling_origin_validation,
    summarize_rolling_origin_folds,
)
from geotestlab.validation.service import run_validation

__all__ = [
    "RELIABILITY_THRESHOLDS",
    "InsufficientPrePeriodError",
    "MissingControlColumnsError",
    "ValidationError",
    "add_lagged_control_features",
    "build_model_matrix",
    "build_regularized_model",
    "calculate_overfit_gap",
    "classify_autocorrelation_risk",
    "classify_overfitting_risk",
    "classify_rolling_bias_risk",
    "classify_rolling_validation_error",
    "classify_validation_method",
    "combine_reliability_ratings",
    "compute_metrics",
    "dates_are_contiguous",
    "durbin_watson_stat",
    "get_frequency_config",
    "get_reliability_drivers",
    "infer_time_series_frequency",
    "rolling_origin_validation",
    "run_placebo_windows",
    "run_validation",
    "safe_tscv",
    "smape",
    "summarize_placebo_results",
    "summarize_rolling_origin_folds",
    "CounterfactualConfidence",
    "FrequencyConfig",
    "ModelMatrixDiagnostics",
    "PlaceboDiagnostics",
    "RegularisationDiagnostics",
    "RollingOriginDiagnostics",
    "ValidationConfig",
    "ValidationPeriods",
    "ValidationResult",
]
