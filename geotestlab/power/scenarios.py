"""Candidate test-share and duration scenario sizing.

This module constructs candidate designs around the production power contract.
It deliberately delegates constraint semantics to the matching package and
delegates power calculation to ``geotestlab.power.production``. Market share
is always based on an explicit regional weight, never on region counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from geotestlab.data import MarketSizeMeasure, RegionalKPIDataset
from geotestlab.matching import (
    MatchConfig,
    MatchConstraints,
    basic_strategy,
    build_kpi_pattern_agg_df,
    build_kpi_pattern_wide_from_regional,
    calculate_metrics,
    find_guided_test_group,
    fit_structural_stats,
    impute_missing_features,
    index_kpi_series_to_100,
    intermediate_strategy,
    nearest_neighbor_start,
    preprocess_data,
    retain_kpi_dates,
    stochastic_genetic_search,
    validate_constraints,
)
from geotestlab.power.production import (
    ProductionPowerConfig,
    ProductionPowerResult,
    run_production_power,
)
from geotestlab.validation import run_validation
from geotestlab.validation.frequency import get_frequency_config
from geotestlab.validation.models import ValidationConfig, ValidationPeriods

DesignAssessor = Callable[
    [tuple[str, ...], tuple[str, ...], tuple[pd.Timestamp, ...]], "DesignAssessment"
]
PowerRunner = Callable[[ProductionPowerConfig], ProductionPowerResult]


@dataclass(frozen=True)
class CandidateDesignRequest:
    """Typed request passed through candidate control-selection seams."""

    metric: str
    requested_share: float
    actual_share: float
    duration_periods: int
    historical_start: pd.Timestamp
    historical_end: pd.Timestamp
    historical_holdout_dates: tuple[pd.Timestamp, ...]
    test_regions: tuple[str, ...]
    eligible_control_regions: tuple[str, ...]
    locked_control_regions: tuple[str, ...]
    constraints: MatchConstraints
    market_size_measure: str
    frequency: str
    validation_method: str
    matching_strategy: str
    random_seed: int
    match_config: MatchConfig


@dataclass(frozen=True)
class ControlSelection:
    """Matched-control output with explicit status and provenance."""

    control_regions: tuple[str, ...]
    match_status: str
    match_metrics: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    provenance: dict = field(default_factory=dict)


ControlSelector = Callable[[RegionalKPIDataset, CandidateDesignRequest], ControlSelection]
ValidationRunner = Callable[
    [RegionalKPIDataset, CandidateDesignRequest, "CandidateDesign"], "DesignAssessment"
]
DesignBuilder = Callable[[RegionalKPIDataset, CandidateDesignRequest], "CandidateDesign"]


@dataclass(frozen=True)
class DesignAssessment:
    """Match and historical-counterfactual status retained by a candidate."""

    match_status: str = "not_evaluated"
    counterfactual_status: str = "not_evaluated"
    match_metrics: dict = field(default_factory=dict)
    counterfactual_metrics: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    matching_method: str | None = None
    matching_seed: int | None = None
    control_selection_provenance: dict = field(default_factory=dict)
    validation_method: str | None = None

    @property
    def passes_quality(self) -> bool:
        return self.match_status in {"pass", "supported"} and self.counterfactual_status in {
            "pass",
            "supported",
        }


@dataclass(frozen=True)
class CandidateDesign:
    """Complete candidate design before power is attached."""

    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    assessment: DesignAssessment


@dataclass(frozen=True)
class ScenarioSizingConfig:
    """Explicit candidate-grid, weight and constraint settings."""

    target_shares: tuple[float, ...] = (0.10, 0.20, 0.30, 0.40, 0.50)
    durations: tuple[int, ...] = (2, 4, 6, 8, 12)
    historical_end: object | None = None
    metric_value: str | None = None
    market_size_measure: MarketSizeMeasure = MarketSizeMeasure.HISTORICAL_KPI_VOLUME
    regional_weights: Mapping[str, float] | None = None
    constraints: MatchConstraints = field(default_factory=MatchConstraints)
    locked_test_regions: tuple[str, ...] = ()
    locked_control_regions: tuple[str, ...] = ()
    share_tolerance: float = 0.05
    search_iterations: int = 2000
    random_seed: int = 42
    objective: str | None = None
    power_template: ProductionPowerConfig | None = None
    matching_strategy: str = "intermediate"
    validation_method: str = "enet"
    match_config: MatchConfig = field(default_factory=MatchConfig)
    control_selector: ControlSelector | None = None
    design_builder: DesignBuilder | None = None
    validation_runner: ValidationRunner | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.market_size_measure, MarketSizeMeasure):
            object.__setattr__(
                self, "market_size_measure", MarketSizeMeasure(self.market_size_measure)
            )


@dataclass(frozen=True)
class PowerScenarioCandidate:
    """One requested-share/duration design and its retained evidence."""

    requested_share: float
    actual_share: float
    share_difference: float
    market_size_measure: str
    duration_periods: int
    planned_test_dates: tuple[str, ...]
    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    design_assessment: DesignAssessment
    power_result: ProductionPowerResult | None = None
    recommendation_eligible: bool = False
    recommendation_blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """Return a JSON-safe candidate export."""

        return {
            "requested_share": float(self.requested_share),
            "actual_share": float(self.actual_share),
            "share_difference": float(self.share_difference),
            "market_size_measure": self.market_size_measure,
            "duration_periods": int(self.duration_periods),
            "planned_test_dates": list(self.planned_test_dates),
            "test_regions": list(self.test_regions),
            "control_regions": list(self.control_regions),
            "design_assessment": {
                "match_status": self.design_assessment.match_status,
                "counterfactual_status": self.design_assessment.counterfactual_status,
                "match_metrics": dict(self.design_assessment.match_metrics),
                "counterfactual_metrics": dict(self.design_assessment.counterfactual_metrics),
                "warnings": list(self.design_assessment.warnings),
                "blockers": list(self.design_assessment.blockers),
                "matching_method": self.design_assessment.matching_method,
                "matching_seed": self.design_assessment.matching_seed,
                "validation_method": self.design_assessment.validation_method,
                "control_selection_provenance": dict(
                    self.design_assessment.control_selection_provenance
                ),
            },
            "power_result": self.power_result.to_dict() if self.power_result else None,
            "recommendation_eligible": bool(self.recommendation_eligible),
            "recommendation_blockers": list(self.recommendation_blockers),
        }


@dataclass(frozen=True)
class ScenarioSizingResult:
    """All candidate designs plus an optional explicit-objective selection."""

    market_size_measure: str
    metric: str
    total_market_size: float
    candidates: tuple[PowerScenarioCandidate, ...]
    selected_candidate_index: int | None = None
    objective: str | None = None

    @property
    def selected_candidate(self) -> PowerScenarioCandidate | None:
        if self.selected_candidate_index is None:
            return None
        return self.candidates[self.selected_candidate_index]

    def to_dict(self) -> dict:
        return {
            "market_size_measure": self.market_size_measure,
            "metric": self.metric,
            "total_market_size": float(self.total_market_size),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_candidate_index": self.selected_candidate_index,
            "objective": self.objective,
        }


def _selected_metric(dataset: RegionalKPIDataset, config: ScenarioSizingConfig) -> str:
    if config.metric_value is not None:
        metric = str(config.metric_value)
        if metric not in dataset.metrics:
            raise ValueError(f"Metric {metric!r} is not present in the canonical dataset")
        return metric
    if len(dataset.metrics) != 1:
        raise ValueError("metric_value is required when the dataset contains multiple metrics")
    return dataset.metrics[0]


def _weights(
    dataset: RegionalKPIDataset,
    metric: str,
    measure: MarketSizeMeasure,
    supplied: Mapping[str, float] | None,
    historical_end: pd.Timestamp | None = None,
) -> pd.Series:
    if measure is MarketSizeMeasure.HISTORICAL_KPI_VOLUME:
        frame = dataset.data[dataset.data["metric"].astype(str) == metric]
        if historical_end is not None:
            dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
            frame = frame.loc[dates <= historical_end]
        weights = frame.groupby("region", sort=True)["kpi"].sum(min_count=1)
    else:
        if supplied is None:
            raise ValueError(
                f"{measure.value} requires explicit regional_weights; weights cannot be inferred"
            )
        weights = pd.Series({str(region): float(value) for region, value in supplied.items()})
        dataset_regions = set(
            dataset.data.loc[dataset.data["metric"].astype(str) == metric, "region"].astype(str)
        )
        if set(weights.index) != dataset_regions:
            missing = sorted(dataset_regions - set(weights.index))
            unknown = sorted(set(weights.index) - dataset_regions)
            details = []
            if missing:
                details.append(f"missing regions {missing}")
            if unknown:
                details.append(f"unknown regions {unknown}")
            raise ValueError(
                "regional_weights must cover exactly the dataset regions ("
                + "; ".join(details)
                + ")"
            )
    weights = weights.astype(float).sort_index()
    if weights.empty or not np.isfinite(weights.to_numpy()).all() or (weights <= 0).any():
        raise ValueError("regional market-size weights must be finite and strictly positive")
    return weights


def _validate_constraints(constraints: MatchConstraints, regions: set[str]) -> None:
    conflicts = validate_constraints(constraints)
    if conflicts:
        details = ", ".join(f"{item.region}: {item.fields}" for item in conflicts)
        raise ValueError(f"contradictory region constraints: {details}")
    referenced = {
        region
        for values in (
            constraints.exclude_from_both,
            constraints.force_test_include,
            constraints.test_only_exclude,
            constraints.force_control_include,
            constraints.control_only_exclude,
        )
        for region in values
    }
    unknown = sorted(referenced - regions)
    if unknown:
        raise ValueError(f"constraints reference unknown regions: {unknown}")


def _control_regions(
    regions: set[str],
    test_regions: tuple[str, ...],
    constraints: MatchConstraints,
    locked_control: tuple[str, ...],
) -> tuple[str, ...]:
    if locked_control:
        controls = tuple(sorted(set(locked_control)))
        if set(controls) - regions:
            raise ValueError("locked_control_regions contain unknown regions")
        if set(controls) & set(test_regions):
            raise ValueError("locked_control_regions overlap the candidate test regions")
    else:
        controls = tuple(
            sorted(
                regions
                - set(test_regions)
                - set(constraints.exclude_from_both)
                - set(constraints.control_only_exclude)
                - set(constraints.force_test_include)
            )
        )
    if not controls:
        raise ValueError("no eligible control regions remain for the candidate")
    if set(constraints.force_control_include) - set(controls):
        raise ValueError("force_control_include regions are not all in the candidate controls")
    if set(controls) & set(constraints.exclude_from_both):
        raise ValueError("locked controls include a region excluded from both groups")
    if set(controls) & set(constraints.control_only_exclude):
        raise ValueError("locked controls include a region excluded from control")
    return controls


def _candidate_test_regions(
    weights: pd.Series,
    share: float,
    config: ScenarioSizingConfig,
) -> tuple[str, ...]:
    regions = set(weights.index)
    if config.locked_test_regions:
        test_regions = tuple(sorted(set(config.locked_test_regions)))
        if set(test_regions) - regions:
            raise ValueError("locked_test_regions contain unknown regions")
        if set(test_regions) & set(config.constraints.exclude_from_both):
            raise ValueError("locked_test_regions include a region excluded from both groups")
        if set(test_regions) & set(config.constraints.test_only_exclude):
            raise ValueError("locked_test_regions include a region excluded from test")
        if set(test_regions) & set(config.constraints.force_control_include):
            raise ValueError("locked_test_regions include a forced control region")
        if set(config.constraints.force_test_include) - set(test_regions):
            raise ValueError("locked_test_regions omit a forced test region")
        return test_regions

    frame = pd.DataFrame({"region": weights.index, "Population": weights.to_numpy()})
    test, _actual, _met = find_guided_test_group(
        frame,
        "region",
        float(weights.sum()),
        config.constraints.force_test_include,
        tuple(config.constraints.test_only_exclude) + tuple(config.constraints.exclude_from_both),
        config.constraints.force_control_include,
        tuple(config.constraints.control_only_exclude)
        + tuple(config.constraints.exclude_from_both),
        float(share * 100),
        float(config.share_tolerance * 100),
        search_iterations=config.search_iterations,
        rng=np.random.default_rng(config.random_seed),
    )
    if not test:
        raise ValueError(f"no test-group candidate could be constructed for share {share:.3f}")
    return tuple(sorted(test))


def _duration_dates(
    dataset: RegionalKPIDataset,
    metric: str,
    historical_end: pd.Timestamp,
    duration: int,
) -> tuple[pd.Timestamp, ...]:
    dates = sorted(
        pd.to_datetime(
            dataset.data.loc[
                (dataset.data["metric"].astype(str) == metric)
                & (pd.to_datetime(dataset.data["date"]) > historical_end),
                "date",
            ].unique()
        )
    )
    return tuple(pd.Timestamp(value).normalize() for value in dates)


def _matching_frame(
    dataset: RegionalKPIDataset,
    metric: str,
    historical_end: pd.Timestamp,
    regions: tuple[str, ...],
) -> tuple[pd.DataFrame, list[str], tuple[str, ...], tuple[str, ...]]:
    """Build the existing KPI-pattern matching frame from canonical data."""

    metric_frame = dataset.data[
        (dataset.data["metric"].astype(str) == metric)
        & (pd.to_datetime(dataset.data["date"]).dt.normalize() <= historical_end)
    ].copy()
    dates = tuple(sorted(pd.to_datetime(metric_frame["date"]).dt.normalize().unique()))
    if not dates:
        return pd.DataFrame(), [], tuple(regions), ()

    wide_full = build_kpi_pattern_wide_from_regional(dataset, metric, list(dates))
    wide_retained, incomplete = retain_kpi_dates(wide_full, list(dates))
    indexed = index_kpi_series_to_100(wide_retained)
    indexed_regions = set(indexed.index.astype(str))
    missing_regions = tuple(sorted(set(regions) - indexed_regions))
    if indexed.empty:
        return pd.DataFrame(), [], missing_regions, tuple(incomplete)

    feature_names = [pd.Timestamp(value).date().isoformat() for value in dates]
    raw = wide_retained.loc[indexed.index, list(dates)].copy()
    raw.columns = feature_names
    indexed = indexed.loc[:, list(dates)].copy()
    indexed.columns = feature_names
    agg = build_kpi_pattern_agg_df(
        indexed,
        raw,
        "region",
        feature_names,
    )
    agg["region"] = agg["region"].astype(str)
    return agg, feature_names, missing_regions, tuple(str(value) for value in incomplete)


def _selection_status(
    metrics: dict,
    match_config: MatchConfig,
    warnings: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    mean_abs_smd = float(metrics.get("mean_abs_smd", np.nan))
    if not np.isfinite(mean_abs_smd):
        smd_values = np.asarray(metrics.get("smd_list", ()), dtype=float)
        if smd_values.size and not np.isfinite(smd_values).any():
            return "supported", warnings + (
                "matching features have zero variance across the eligible candidate pool; "
                "SMD is unavailable but the structural distance remains recorded",
            )
        return "fail", warnings + ("matching produced a non-finite mean absolute SMD",)
    if mean_abs_smd <= match_config.smd_good_threshold:
        return "pass", warnings
    if mean_abs_smd <= match_config.smd_high_threshold:
        return "supported", warnings + (
            f"mean absolute SMD {mean_abs_smd:.3f} is above the good-balance threshold "
            f"{match_config.smd_good_threshold:.3f}",
        )
    return "fail", warnings + (
        f"mean absolute SMD {mean_abs_smd:.3f} exceeds the high-balance threshold "
        f"{match_config.smd_high_threshold:.3f}",
    )


def _default_control_selector(
    dataset: RegionalKPIDataset,
    request: CandidateDesignRequest,
) -> ControlSelection:
    """Select controls with the repository's existing KPI-pattern strategies."""

    all_regions = tuple(request.test_regions) + tuple(request.eligible_control_regions)
    agg, features, missing_regions, incomplete_regions = _matching_frame(
        dataset, request.metric, request.historical_end, all_regions
    )
    if agg.empty or not features:
        return ControlSelection(
            control_regions=(),
            match_status="fail",
            blockers=("no complete historical KPI pattern is available for matching",),
            provenance={"strategy": request.matching_strategy, "seed": request.random_seed},
        )
    missing_test = sorted(set(request.test_regions) & set(missing_regions))
    if missing_test:
        return ControlSelection(
            control_regions=(),
            match_status="fail",
            blockers=(
                "candidate test regions have incomplete historical KPI patterns: "
                + ", ".join(missing_test),
            ),
            provenance={"strategy": request.matching_strategy, "seed": request.random_seed},
        )

    eligible = [
        region
        for region in request.eligible_control_regions
        if region in set(agg["region"]) and region not in set(incomplete_regions)
    ]
    warnings: list[str] = []
    missing_controls = sorted(set(request.eligible_control_regions) - set(eligible))
    if missing_controls:
        warnings.append(
            "excluded incomplete control candidates from matching: " + ", ".join(missing_controls)
        )
    if not eligible:
        return ControlSelection(
            control_regions=(),
            match_status="fail",
            warnings=tuple(warnings),
            blockers=("no complete eligible control regions remain for matching",),
            provenance={"strategy": request.matching_strategy, "seed": request.random_seed},
        )

    test_df = agg[agg["region"].isin(request.test_regions)].copy()
    pool_df = agg[agg["region"].isin(eligible)].copy()
    forced = tuple(sorted(set(request.constraints.force_control_include) & set(eligible)))
    target_count = max(len(request.test_regions), len(forced))
    if request.locked_control_regions:
        controls = tuple(sorted(set(request.locked_control_regions)))
        if set(controls) - set(eligible):
            return ControlSelection(
                control_regions=controls,
                match_status="fail",
                blockers=("locked control regions are not complete eligible candidates",),
                provenance={"strategy": "locked", "seed": request.random_seed},
            )
        selected = controls
        remaining_pool = pool_df.iloc[0:0].copy()
        selected_indices: tuple[str, ...] = selected
    else:
        remaining_pool = pool_df[~pool_df["region"].isin(forced)].copy()
        remaining_count = target_count - len(forced)
        if remaining_count < 0 or remaining_count > len(remaining_pool):
            return ControlSelection(
                control_regions=forced,
                match_status="fail",
                warnings=tuple(warnings),
                blockers=(
                    f"only {len(remaining_pool)} eligible control candidates remain for "
                    f"a {remaining_count}-region matched control set",
                ),
                provenance={"strategy": request.matching_strategy, "seed": request.random_seed},
            )

        eligible_df = pd.concat([test_df, pool_df], ignore_index=True)
        eligible_df = impute_missing_features(eligible_df, features)
        means, stds = fit_structural_stats(eligible_df, features)
        weights = {feature: 1.0 for feature in features}
        means_tuple = tuple(float(means[feature]) for feature in features)
        stds_tuple = tuple(float(stds[feature]) for feature in features)
        _w_vec, p_scaled, t_cent = preprocess_data(
            remaining_pool,
            test_df,
            features,
            weights,
            means_tuple,
            stds_tuple,
        )
        combined = pool_df.set_index("region")

        def score(indices):
            chosen = list(forced) + [str(value) for value in indices]
            return calculate_metrics(
                test_df,
                combined.loc[chosen].reset_index(),
                features,
                weights,
                means,
                stds,
            )

        strategy = request.matching_strategy
        if strategy == "basic":
            selected_indices, _metrics = basic_strategy(
                remaining_pool.set_index("region"),
                p_scaled,
                t_cent,
                remaining_count,
                score,
            )
        elif strategy == "intermediate":
            selected_indices, _metrics, _convergence = intermediate_strategy(
                remaining_pool.set_index("region"),
                p_scaled,
                t_cent,
                remaining_count,
                score,
                request.match_config.max_hill_climbing_swaps,
            )
        elif strategy == "stochastic":
            nn_start = nearest_neighbor_start(
                remaining_pool.set_index("region"), p_scaled, t_cent, remaining_count
            )
            selected_indices, _metrics, _evaluated, _convergence = stochastic_genetic_search(
                remaining_pool.set_index("region"),
                test_df,
                features,
                weights,
                remaining_count,
                calculate_metrics,
                means,
                stds,
                nn_start_idx=nn_start,
                n_iterations=request.match_config.genetic_iterations_default,
                random_state=request.random_seed,
                fast_metrics_fn=score,
            )
        else:
            raise ValueError(
                "matching_strategy must be one of 'basic', 'intermediate' or 'stochastic'"
            )
        selected_indices = tuple(str(value) for value in selected_indices)
        selected = tuple(sorted(set(forced) | set(selected_indices)))

    selected_frame = agg[agg["region"].isin(selected)].copy()
    eligible_df = pd.concat([test_df, pool_df], ignore_index=True)
    eligible_df = impute_missing_features(eligible_df, features)
    means, stds = fit_structural_stats(eligible_df, features)
    metrics = calculate_metrics(
        test_df,
        selected_frame,
        features,
        {feature: 1.0 for feature in features},
        means,
        stds,
    )
    metrics = {
        "weighted_structural_distance": float(metrics["weighted_structural_distance"]),
        "mean_abs_smd": float(metrics["mean_abs_smd"]),
        "smd_list": [float(value) if np.isfinite(value) else None for value in metrics["smd_list"]],
        "control_group_size": len(selected),
        "test_group_size": len(request.test_regions),
    }
    status, status_warnings = _selection_status(metrics, request.match_config, tuple(warnings))
    blockers = () if status != "fail" else status_warnings[-1:]
    return ControlSelection(
        control_regions=selected,
        match_status=status,
        match_metrics=metrics,
        warnings=status_warnings,
        blockers=blockers,
        provenance={
            "strategy": "locked" if request.locked_control_regions else request.matching_strategy,
            "seed": request.random_seed,
            "historical_end": request.historical_end.date().isoformat(),
            "feature_count": len(features),
            "candidate_pool_size": len(eligible),
        },
    )


def _default_validation_runner(
    dataset: RegionalKPIDataset,
    request: CandidateDesignRequest,
    design: CandidateDesign,
) -> DesignAssessment:
    """Run the existing counterfactual validation service for one candidate."""

    frequency_config = get_frequency_config(request.frequency)
    validation_config = ValidationConfig(
        method_name=request.validation_method,
        compute_uplift=False,
        placebo_length_periods=request.duration_periods,
        min_training_periods=frequency_config.default_min_training_periods,
        include_lagged_controls=False,
        time_series_frequency=frequency_config.frequency,
        frequency_config=frequency_config,
    )
    periods = ValidationPeriods(
        pre_start=request.historical_start,
        pre_end=request.historical_end,
        test_start=None,
        test_end=None,
        use_post=False,
        post_start=None,
        post_end=None,
    )
    frame = dataset.data[dataset.data["metric"].astype(str) == request.metric][
        ["region", "date", "kpi"]
    ].copy()
    result = run_validation(
        frame,
        list(design.control_regions),
        list(design.test_regions),
        validation_config,
        periods,
    )
    if not result.ok:
        blockers = tuple(result.blockers or result.errors)
        if result.insufficient_pre_period and not blockers:
            blockers = ("historical counterfactual validation has insufficient pre-period data",)
        return DesignAssessment(
            match_status=design.assessment.match_status,
            counterfactual_status="fail",
            match_metrics=dict(design.assessment.match_metrics),
            warnings=tuple(result.warnings),
            blockers=blockers,
            validation_method=request.validation_method,
        )

    summary = result.summary or {}
    confidence = result.confidence.rating if result.confidence else ""
    counterfactual_status = "fail" if confidence.startswith("🔴") else "pass"
    blockers = (
        ()
        if counterfactual_status == "pass"
        else (f"counterfactual confidence is {confidence or 'unavailable'}",)
    )
    metrics = {
        key: summary[key]
        for key in (
            "corr",
            "r2",
            "smape",
            "rmse",
            "rolling_smape_mean",
            "rolling_rmse_mean",
            "counterfactual_reliability",
            "reliability_drivers",
        )
        if key in summary
    }
    return DesignAssessment(
        match_status=design.assessment.match_status,
        counterfactual_status=counterfactual_status,
        match_metrics=dict(design.assessment.match_metrics),
        counterfactual_metrics=metrics,
        warnings=tuple(result.warnings),
        blockers=blockers,
        validation_method=request.validation_method,
    )


def build_candidate_design(
    dataset: RegionalKPIDataset,
    request: CandidateDesignRequest,
    *,
    control_selector: ControlSelector | None = None,
    validation_runner: ValidationRunner | None = None,
    design_assessor: DesignAssessor | None = None,
) -> CandidateDesign:
    """Build, match and validate one candidate through typed seams."""

    selector = control_selector or _default_control_selector
    selection = selector(dataset, request)
    if not isinstance(selection, ControlSelection):
        raise TypeError("control_selector must return ControlSelection")
    controls = tuple(selection.control_regions)
    if set(controls) & set(request.test_regions):
        raise ValueError("control_selector returned regions that overlap the candidate test set")
    if set(controls) - set(request.eligible_control_regions):
        raise ValueError("control_selector returned ineligible control regions")

    initial = DesignAssessment(
        match_status=selection.match_status,
        match_metrics=dict(selection.match_metrics),
        warnings=tuple(selection.warnings),
        blockers=tuple(selection.blockers),
        matching_method=request.matching_strategy,
        matching_seed=request.random_seed,
        control_selection_provenance=dict(selection.provenance),
    )
    design = CandidateDesign(
        test_regions=tuple(request.test_regions),
        control_regions=controls,
        assessment=initial,
    )
    if selection.blockers or not controls:
        return design

    if design_assessor is not None:
        assessed = _assessment(
            design_assessor,
            design.test_regions,
            design.control_regions,
            request.historical_holdout_dates,
        )
    elif validation_runner is not None:
        assessed = validation_runner(dataset, request, design)
        if not isinstance(assessed, DesignAssessment):
            raise TypeError("validation_runner must return DesignAssessment")
    else:
        assessed = _default_validation_runner(dataset, request, design)

    merged_warnings = tuple(dict.fromkeys(initial.warnings + tuple(assessed.warnings)))
    merged_blockers = tuple(dict.fromkeys(initial.blockers + tuple(assessed.blockers)))
    return CandidateDesign(
        test_regions=design.test_regions,
        control_regions=design.control_regions,
        assessment=replace(
            assessed,
            match_status=initial.match_status,
            match_metrics={**initial.match_metrics, **assessed.match_metrics},
            warnings=merged_warnings,
            blockers=merged_blockers,
            matching_method=initial.matching_method,
            matching_seed=initial.matching_seed,
            control_selection_provenance=initial.control_selection_provenance,
            validation_method=assessed.validation_method or request.validation_method,
        ),
    )


def _assessment(
    assessor: DesignAssessor | None,
    test_regions: tuple[str, ...],
    control_regions: tuple[str, ...],
    test_dates: tuple[pd.Timestamp, ...],
) -> DesignAssessment:
    if assessor is None:
        return DesignAssessment(
            blockers=("match/counterfactual assessment was not supplied",),
        )
    result = assessor(test_regions, control_regions, test_dates)
    if not isinstance(result, DesignAssessment):
        raise TypeError("design_assessor must return DesignAssessment")
    return result


def _recommendation_state(
    assessment: DesignAssessment,
    power: ProductionPowerResult | None,
    target_power: float | None,
) -> tuple[bool, tuple[str, ...]]:
    blockers: list[str] = []
    blockers.extend(assessment.blockers)
    if not assessment.passes_quality:
        blockers.append("match/counterfactual quality does not pass")
    if power is None:
        blockers.append("power was not run")
    else:
        if not power.completed:
            blockers.append("power result is incomplete")
        if not power.usable_for_recommendation:
            blockers.append(f"power support status is {power.support_status}")
        if target_power is not None and any(
            not np.isfinite(value) or value < target_power
            for value in power.power_at_target_effects
        ):
            blockers.append("power at one or more target effects is below target power")
        blockers.extend(power.blockers)
    return not blockers, tuple(dict.fromkeys(blockers))


def size_power_scenarios(
    dataset: RegionalKPIDataset,
    config: ScenarioSizingConfig,
    *,
    design_assessor: DesignAssessor | None = None,
    power_runner: PowerRunner | None = None,
) -> ScenarioSizingResult:
    """Build and evaluate candidate test-share/duration designs.

    ``design_assessor`` is the integration seam for existing matching and
    counterfactual-validation services. If omitted, candidates are retained
    but never recommended. ``power_runner`` defaults to the approved
    production power service using ``config.power_template``.
    """

    metric = _selected_metric(dataset, config)
    if config.historical_end is None:
        if config.power_template is None:
            raise ValueError("historical_end is required when no power_template is supplied")
        historical_end = pd.Timestamp(config.power_template.historical_end).normalize()
    else:
        historical_end = pd.Timestamp(config.historical_end).normalize()
    if config.power_template is not None:
        template_end = pd.Timestamp(config.power_template.historical_end).normalize()
        if template_end != historical_end:
            raise ValueError(
                "ScenarioSizingConfig.historical_end must match power_template.historical_end"
            )
    weights = _weights(
        dataset,
        metric,
        config.market_size_measure,
        config.regional_weights,
        historical_end,
    )
    _validate_constraints(config.constraints, set(weights.index))
    if config.share_tolerance < 0 or config.share_tolerance >= 1:
        raise ValueError("share_tolerance must be in [0, 1)")
    if not config.target_shares or any(share <= 0 or share >= 1 for share in config.target_shares):
        raise ValueError("target_shares must be strictly between 0 and 1")
    if not config.durations or any(int(duration) <= 0 for duration in config.durations):
        raise ValueError("durations must contain positive period counts")

    runner = power_runner
    candidates: list[PowerScenarioCandidate] = []
    for requested_share in config.target_shares:
        test_regions = _candidate_test_regions(weights, float(requested_share), config)
        actual_share = float(weights.loc[list(test_regions)].sum() / weights.sum())
        eligible_controls = _control_regions(
            set(weights.index),
            test_regions,
            config.constraints,
            tuple(config.locked_control_regions),
        )
        for duration in config.durations:
            available_dates = _duration_dates(dataset, metric, historical_end, int(duration))
            if len(available_dates) < int(duration):
                test_dates = ()
                assessment = DesignAssessment(
                    blockers=(
                        f"only {len(available_dates)} post-history dates are available; "
                        f"duration {duration} cannot be built",
                    )
                )
                candidate_design = CandidateDesign(
                    test_regions=test_regions,
                    control_regions=(),
                    assessment=assessment,
                )
            else:
                test_dates = available_dates[: int(duration)]
                historical_start = (
                    pd.Timestamp(config.power_template.historical_start).normalize()
                    if config.power_template is not None
                    else pd.Timestamp(
                        dataset.data.loc[
                            (dataset.data["metric"].astype(str) == metric)
                            & (
                                pd.to_datetime(dataset.data["date"]).dt.normalize()
                                <= historical_end
                            ),
                            "date",
                        ].min()
                    ).normalize()
                )
                request = CandidateDesignRequest(
                    metric=metric,
                    requested_share=float(requested_share),
                    actual_share=actual_share,
                    duration_periods=int(duration),
                    historical_start=historical_start,
                    historical_end=historical_end,
                    historical_holdout_dates=tuple(test_dates),
                    test_regions=test_regions,
                    eligible_control_regions=tuple(eligible_controls),
                    locked_control_regions=tuple(config.locked_control_regions),
                    constraints=config.constraints,
                    market_size_measure=config.market_size_measure.value,
                    frequency=(
                        config.power_template.frequency
                        if config.power_template is not None
                        else "weekly"
                    ),
                    validation_method=config.validation_method,
                    matching_strategy=config.matching_strategy,
                    random_seed=config.random_seed,
                    match_config=config.match_config,
                )
                if config.design_builder is not None:
                    candidate_design = config.design_builder(dataset, request)
                    if not isinstance(candidate_design, CandidateDesign):
                        raise TypeError("design_builder must return CandidateDesign")
                    if tuple(candidate_design.test_regions) != tuple(request.test_regions):
                        raise ValueError("design_builder must retain the requested test regions")
                    if set(candidate_design.control_regions) & set(request.test_regions):
                        raise ValueError("design_builder returned overlapping test/control regions")
                    if set(candidate_design.control_regions) - set(
                        request.eligible_control_regions
                    ):
                        raise ValueError("design_builder returned ineligible control regions")
                else:
                    candidate_design = build_candidate_design(
                        dataset,
                        request,
                        control_selector=config.control_selector,
                        validation_runner=config.validation_runner,
                        design_assessor=design_assessor,
                    )
                assessment = candidate_design.assessment
            if abs(actual_share - float(requested_share)) > config.share_tolerance:
                share_blocker = (
                    f"achieved market share {actual_share:.3f} is outside the requested "
                    f"share tolerance of {config.share_tolerance:.3f}"
                )
                assessment = replace(
                    assessment,
                    blockers=tuple(dict.fromkeys(assessment.blockers + (share_blocker,))),
                )
                candidate_design = replace(candidate_design, assessment=assessment)
            power_result = None
            planned_dates = ()
            if config.power_template is not None:
                template_dates = tuple(config.power_template.planned_test_dates)
                if len(template_dates) == int(duration):
                    planned_dates = template_dates
            if (
                (config.power_template is not None or runner is not None)
                and test_dates
                and candidate_design.control_regions
            ):
                if config.power_template is None:
                    raise ValueError("power_template is required when power_runner is supplied")
                candidate_config = replace(
                    config.power_template,
                    metric_value=metric,
                    test_regions=test_regions,
                    control_regions=candidate_design.control_regions,
                    historical_holdout_dates=test_dates,
                    planned_duration_periods=int(duration),
                    planned_test_dates=planned_dates,
                )
                if runner is None:
                    power_result = run_production_power(dataset, candidate_config)
                else:
                    power_result = runner(candidate_config)
            eligible, blockers = _recommendation_state(
                assessment,
                power_result,
                config.power_template.target_power if config.power_template else None,
            )
            candidates.append(
                PowerScenarioCandidate(
                    requested_share=float(requested_share),
                    actual_share=actual_share,
                    share_difference=actual_share - float(requested_share),
                    market_size_measure=config.market_size_measure.value,
                    duration_periods=int(duration),
                    planned_test_dates=tuple(value.isoformat() for value in planned_dates),
                    test_regions=tuple(candidate_design.test_regions),
                    control_regions=tuple(candidate_design.control_regions),
                    design_assessment=assessment,
                    power_result=power_result,
                    recommendation_eligible=eligible,
                    recommendation_blockers=blockers,
                )
            )

    selected_index = None
    if config.objective is not None:
        selected_index = select_smallest_qualifying(candidates, config.objective)
    return ScenarioSizingResult(
        market_size_measure=config.market_size_measure.value,
        metric=metric,
        total_market_size=float(weights.sum()),
        candidates=tuple(candidates),
        selected_candidate_index=selected_index,
        objective=config.objective,
    )


def select_smallest_qualifying(
    candidates: list[PowerScenarioCandidate] | tuple[PowerScenarioCandidate, ...],
    objective: str,
) -> int | None:
    """Select a qualifying candidate under an explicit optimisation objective."""

    eligible = [
        (index, candidate)
        for index, candidate in enumerate(candidates)
        if candidate.recommendation_eligible
    ]
    if objective == "smallest_test_share_then_duration":

        def key(item):
            return (item[1].actual_share, item[1].duration_periods, item[0])

    elif objective == "shortest_duration_then_test_share":

        def key(item):
            return (item[1].duration_periods, item[1].actual_share, item[0])
    else:
        raise ValueError(
            "unknown optimisation objective; expected "
            "'smallest_test_share_then_duration' or 'shortest_duration_then_test_share'"
        )
    return min(eligible, key=key)[0] if eligible else None
