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
from geotestlab.matching import MatchConstraints, find_guided_test_group, validate_constraints
from geotestlab.power.production import (
    ProductionPowerConfig,
    ProductionPowerResult,
    run_production_power,
)

DesignAssessor = Callable[
    [tuple[str, ...], tuple[str, ...], tuple[pd.Timestamp, ...]], "DesignAssessment"
]
PowerRunner = Callable[[ProductionPowerConfig], ProductionPowerResult]


@dataclass(frozen=True)
class DesignAssessment:
    """Match and historical-counterfactual status retained by a candidate."""

    match_status: str = "not_evaluated"
    counterfactual_status: str = "not_evaluated"
    match_metrics: dict = field(default_factory=dict)
    counterfactual_metrics: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def passes_quality(self) -> bool:
        return self.match_status in {"pass", "supported"} and self.counterfactual_status in {
            "pass",
            "supported",
        }


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
    if len(dates) < duration:
        raise ValueError(
            f"only {len(dates)} post-history dates are available; duration {duration} cannot be built"
        )
    return tuple(pd.Timestamp(value).normalize() for value in dates[:duration])


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
        controls = _control_regions(
            set(weights.index),
            test_regions,
            config.constraints,
            tuple(config.locked_control_regions),
        )
        for duration in config.durations:
            test_dates = _duration_dates(dataset, metric, historical_end, int(duration))
            assessment = _assessment(design_assessor, test_regions, controls, test_dates)
            power_result = None
            if config.power_template is not None or runner is not None:
                if config.power_template is None:
                    raise ValueError("power_template is required when power_runner is supplied")
                candidate_config = replace(
                    config.power_template,
                    metric_value=metric,
                    test_regions=test_regions,
                    control_regions=controls,
                    test_dates=test_dates,
                )
                power_result = (runner or run_production_power)(candidate_config)
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
                    planned_test_dates=tuple(value.isoformat() for value in test_dates),
                    test_regions=test_regions,
                    control_regions=controls,
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
