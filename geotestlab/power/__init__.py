"""Power-analysis methodology spike (Stage 5) — pure prototype.

This package is a *spike*: it produces decision evidence for the approved
prospective Power Analysis and Test Sizing product (see
``docs/product/power-analysis-and-test-sizing.md``). It is NOT the production
power engine and must not be extended into one without an approved methodology
decision. No Streamlit imports.
"""

from geotestlab.power.alignment import build_date_keyed_matrix
from geotestlab.power.detection import (
    critical_values,
    power_from_totals,
    validate_detection_criterion,
)
from geotestlab.power.fit_comparison import (
    CONTROLLED_FIT_SCENARIOS,
    build_fit_scenario,
    compare_fit_methods,
)
from geotestlab.power.mde import find_mde
from geotestlab.power.methods import (
    DEFAULT_MAX_CONDITION_NUMBER,
    FALLBACK_FIT_METHOD,
    FIT_METHOD_NAMES,
    METHODS,
    CounterfactualFit,
    build_placebo_windows,
    fit_ar1,
    fit_counterfactual,
    model_simulation,
    placebo_empirical,
    project_counterfactual,
    residual_simulation,
)
from geotestlab.power.models import (
    DETECTION_CRITERIA,
    EFFECT_INJECTIONS,
    EFFECT_SHAPES,
    METHODOLOGY_VERSION,
    SIDES,
    PowerConfig,
    PowerResult,
    validate_effect_shape,
)
from geotestlab.power.models import (
    METHODS as METHOD_NAMES,
)
from geotestlab.power.service import run_power_analysis
from geotestlab.power.synthetic import (
    SyntheticCase,
    analytic_power,
    analytic_total_variance,
    generate_synthetic_case,
)
from geotestlab.power.uncertainty import clopper_pearson, power_with_ci

__all__ = [
    "CONTROLLED_FIT_SCENARIOS",
    "CounterfactualFit",
    "DEFAULT_MAX_CONDITION_NUMBER",
    "DETECTION_CRITERIA",
    "EFFECT_INJECTIONS",
    "EFFECT_SHAPES",
    "FALLBACK_FIT_METHOD",
    "FIT_METHOD_NAMES",
    "METHODOLOGY_VERSION",
    "METHODS",
    "METHOD_NAMES",
    "PowerConfig",
    "PowerResult",
    "SIDES",
    "SyntheticCase",
    "analytic_power",
    "analytic_total_variance",
    "build_date_keyed_matrix",
    "build_fit_scenario",
    "build_placebo_windows",
    "clopper_pearson",
    "compare_fit_methods",
    "critical_values",
    "find_mde",
    "fit_ar1",
    "fit_counterfactual",
    "generate_synthetic_case",
    "model_simulation",
    "placebo_empirical",
    "power_from_totals",
    "power_with_ci",
    "project_counterfactual",
    "residual_simulation",
    "run_power_analysis",
    "validate_detection_criterion",
    "validate_effect_shape",
]
