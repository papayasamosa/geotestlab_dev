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
from geotestlab.power.evidence_v2 import (
    ADDITIONAL_SAFETY_SCENARIOS,
    EVIDENCE_SUITE_VERSION,
    EXPECTED_SUPPORTED_CORE_SCENARIOS,
    PROPOSED_ACCEPTANCE_THRESHOLDS,
    build_concise_summary,
    build_v2_scenario,
    run_evidence_v2,
    summarise_v2,
)
from geotestlab.power.fit_comparison import (
    CONTROLLED_FIT_SCENARIOS,
    build_fit_scenario,
    compare_bayesian_evidence,
    compare_fit_methods,
)
from geotestlab.power.market_evidence import (
    MARKET_SCENARIOS,
    MarketScenario,
    build_market_scenario,
    combine_evidence,
    generate_market_case,
    noise_sum_simulator,
    reference_mde,
    reference_null_sd,
    reference_power,
    run_market_evidence,
    strip_timing,
    summarise_evidence,
    write_evidence_report,
)
from geotestlab.power.mde import find_mde, validate_mde_config
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
from geotestlab.power.random import child_rngs
from geotestlab.power.service import run_power_analysis
from geotestlab.power.synthetic import (
    SyntheticCase,
    analytic_power,
    analytic_total_variance,
    generate_synthetic_case,
)
from geotestlab.power.uncertainty import clopper_pearson, power_with_ci

__all__ = [
    "ADDITIONAL_SAFETY_SCENARIOS",
    "CONTROLLED_FIT_SCENARIOS",
    "CounterfactualFit",
    "DEFAULT_MAX_CONDITION_NUMBER",
    "DETECTION_CRITERIA",
    "EFFECT_INJECTIONS",
    "EFFECT_SHAPES",
    "EVIDENCE_SUITE_VERSION",
    "EXPECTED_SUPPORTED_CORE_SCENARIOS",
    "FALLBACK_FIT_METHOD",
    "FIT_METHOD_NAMES",
    "MARKET_SCENARIOS",
    "METHODOLOGY_VERSION",
    "METHODS",
    "METHOD_NAMES",
    "MarketScenario",
    "PROPOSED_ACCEPTANCE_THRESHOLDS",
    "PowerConfig",
    "PowerResult",
    "SIDES",
    "SyntheticCase",
    "analytic_power",
    "analytic_total_variance",
    "build_concise_summary",
    "build_date_keyed_matrix",
    "build_fit_scenario",
    "build_market_scenario",
    "build_placebo_windows",
    "build_v2_scenario",
    "child_rngs",
    "clopper_pearson",
    "combine_evidence",
    "compare_bayesian_evidence",
    "compare_fit_methods",
    "critical_values",
    "find_mde",
    "fit_ar1",
    "fit_counterfactual",
    "generate_market_case",
    "generate_synthetic_case",
    "model_simulation",
    "noise_sum_simulator",
    "placebo_empirical",
    "power_from_totals",
    "power_with_ci",
    "project_counterfactual",
    "reference_mde",
    "reference_null_sd",
    "reference_power",
    "residual_simulation",
    "run_evidence_v2",
    "run_market_evidence",
    "run_power_analysis",
    "strip_timing",
    "summarise_evidence",
    "summarise_v2",
    "validate_detection_criterion",
    "validate_effect_shape",
    "validate_mde_config",
    "write_evidence_report",
]
