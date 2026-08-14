"""GeoTestLab matching core.

Pure matching logic extracted from the Streamlit monolith (``geotestmatch.py``).
Every module in this package is free of Streamlit imports so the matching core
can be unit-tested and reused independently of the UI.

Modules:
- ``models`` — immutable typed objects (``MatchConfig``, ``FeatureWeightConfig``,
  ``MatchConstraints``, ``MatchDiagnostics``, ``MatchResult``) + shared constants.
- ``structural`` — structural feature preparation (market-dataframe cleaning,
  weighted aggregation, median imputation).
- ``metrics`` — population-weighted profiles, SMD, Weighted Structural Distance,
  vectorised scorer, NN pre-processing.
- ``kpi_pattern`` — KPI-pattern feature preparation (index-to-100 pattern distance).
- ``constraints`` — guided 'Set Rules & Auto-Build Groups' search + conflict validation.
- ``strategies`` — Basic (Greedy NN), Intermediate (Hill Climbing), Advanced
  (Stochastic Genetic Search).
"""

from . import constraints, kpi_pattern, metrics, models, strategies, structural
from .constraints import (
    GUIDED_SEARCH_CONFIG,
    ConstraintConflict,
    GuidedSearchConfig,
    find_guided_test_group,
    validate_constraints,
)
from .kpi_pattern import (
    build_kpi_pattern_agg_df,
    build_kpi_pattern_wide,
    build_kpi_pattern_wide_from_regional,
    coerce_kpi_date_values,
    filter_kpi_rows,
    index_kpi_series_to_100,
    read_kpi_pattern_excel,
    retain_kpi_dates,
)
from .metrics import (
    calculate_experiment_population_coverage,
    calculate_metrics,
    calculate_metrics_from_flat,
    fit_structural_stats,
    make_fast_metrics_fn,
    preprocess_data,
    weighted_profile,
)
from .models import (
    ADOBE_COL,
    POPULATION_COL,
    POPULATION_COL_RAW,
    FeatureWeightConfig,
    MatchConfig,
    MatchConstraints,
    MatchDiagnostics,
    MatchResult,
)
from .strategies import (
    basic_strategy,
    intermediate_strategy,
    nearest_neighbor_start,
    stochastic_genetic_search,
    to_match_result,
)
from .structural import (
    aggregate_market_data,
    get_base_geography_column,
    get_grouping_columns,
    get_numeric_metric_columns,
    get_population_column,
    impute_missing_features,
    normalise_column_names,
    prepare_market_dataframe,
    standardise_population_column,
    weighted_average_vectorized,
)

__all__ = [
    "constraints",
    "kpi_pattern",
    "metrics",
    "models",
    "strategies",
    "structural",
    "ADOBE_COL",
    "POPULATION_COL",
    "POPULATION_COL_RAW",
    "FeatureWeightConfig",
    "MatchConfig",
    "MatchConstraints",
    "MatchDiagnostics",
    "MatchResult",
    "GuidedSearchConfig",
    "GUIDED_SEARCH_CONFIG",
    "ConstraintConflict",
    "validate_constraints",
    "find_guided_test_group",
    "normalise_column_names",
    "get_population_column",
    "get_base_geography_column",
    "get_grouping_columns",
    "standardise_population_column",
    "get_numeric_metric_columns",
    "prepare_market_dataframe",
    "weighted_average_vectorized",
    "aggregate_market_data",
    "impute_missing_features",
    "weighted_profile",
    "fit_structural_stats",
    "calculate_metrics",
    "calculate_metrics_from_flat",
    "make_fast_metrics_fn",
    "preprocess_data",
    "calculate_experiment_population_coverage",
    "read_kpi_pattern_excel",
    "filter_kpi_rows",
    "coerce_kpi_date_values",
    "build_kpi_pattern_wide",
    "build_kpi_pattern_wide_from_regional",
    "retain_kpi_dates",
    "index_kpi_series_to_100",
    "build_kpi_pattern_agg_df",
    "basic_strategy",
    "intermediate_strategy",
    "nearest_neighbor_start",
    "stochastic_genetic_search",
    "to_match_result",
]
