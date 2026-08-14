"""Integrated design recommendation contracts.

The recommendation layer consumes explicit candidate-level statuses from the
matching, counterfactual, power, delivery and effect stages.  It deliberately
does not turn those stages into a composite score: each gate remains visible
in the assessment and in the JSON export.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

RECOMMENDATION_SCHEMA_VERSION = "design-recommendation/v1"


class RecommendationObjective(StrEnum):
    """Supported optimisation objectives for qualifying designs."""

    SMALLEST_QUALIFYING_DESIGN = "smallest_qualifying_design"
    LEAST_COST_QUALIFYING_DESIGN = "least_cost_qualifying_design"


class RecommendationStatus(StrEnum):
    """Outcome of the explicit candidate comparison."""

    RECOMMENDED = "recommended"
    CONDITIONAL = "conditional"
    NO_QUALIFYING_DESIGN = "no_qualifying_design"
    INCOMPLETE = "incomplete"


_PASS_STATUSES = {"pass", "supported", "credible", "valid", "complete"}


def _value(value: Any) -> Any:
    """Convert enums and common containers into deterministic JSON values."""

    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _value(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_value(item) for item in value)
    return value


def _status(value: Any) -> str:
    return str(value.value if isinstance(value, StrEnum) else value).strip().lower()


@dataclass(frozen=True)
class DesignScenario:
    """One complete design candidate with separately supplied gate evidence."""

    scenario_id: str
    size_metric: float
    duration_periods: int
    cost: float | None
    match_status: str
    counterfactual_status: str
    power_status: str
    power_usable: bool
    power_meets_target: bool | None
    delivery_status: str
    effect_status: str
    effect_meets_mde: bool | None
    region_constraints_status: str = "not_evaluated"
    history_periods: int | None = None
    notes: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be empty")
        if not math.isfinite(float(self.size_metric)) or float(self.size_metric) < 0:
            raise ValueError("size_metric must be a finite non-negative number")
        if int(self.duration_periods) <= 0:
            raise ValueError("duration_periods must be positive")
        if self.cost is not None and (
            not math.isfinite(float(self.cost)) or float(self.cost) < 0
        ):
            raise ValueError("cost must be finite and non-negative when supplied")
        if self.history_periods is not None and int(self.history_periods) < 0:
            raise ValueError("history_periods must be non-negative when supplied")
        object.__setattr__(self, "scenario_id", self.scenario_id.strip())
        object.__setattr__(self, "duration_periods", int(self.duration_periods))
        object.__setattr__(self, "size_metric", float(self.size_metric))
        if self.cost is not None:
            object.__setattr__(self, "cost", float(self.cost))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

    def to_dict(self) -> dict[str, Any]:
        """Return all candidate inputs, including separate gate statuses."""

        return {
            "scenario_id": self.scenario_id,
            "size_metric": self.size_metric,
            "duration_periods": self.duration_periods,
            "cost": self.cost,
            "match_status": _status(self.match_status),
            "counterfactual_status": _status(self.counterfactual_status),
            "power_status": _status(self.power_status),
            "power_usable": bool(self.power_usable),
            "power_meets_target": self.power_meets_target,
            "delivery_status": _status(self.delivery_status),
            "effect_status": _status(self.effect_status),
            "effect_meets_mde": self.effect_meets_mde,
            "region_constraints_status": _status(self.region_constraints_status),
            "history_periods": self.history_periods,
            "notes": list(self.notes),
            "metadata": _value(self.metadata),
        }


@dataclass(frozen=True)
class ScenarioAssessment:
    """Gate-by-gate assessment retained for review and export."""

    scenario_id: str
    qualifies: bool
    conditional: bool
    gate_statuses: Mapping[str, str]
    gate_passes: Mapping[str, bool]
    limiting_factors: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    size_metric: float = 0.0
    duration_periods: int = 0
    cost: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "qualifies": self.qualifies,
            "conditional": self.conditional,
            "gate_statuses": dict(sorted(self.gate_statuses.items())),
            "gate_passes": dict(sorted(self.gate_passes.items())),
            "limiting_factors": list(self.limiting_factors),
            "conditions": list(self.conditions),
            "size_metric": self.size_metric,
            "duration_periods": self.duration_periods,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class RecommendationResult:
    """Auditable comparison result with an optional selected candidate."""

    schema_version: str
    status: RecommendationStatus
    objective: RecommendationObjective
    input_fingerprint: str
    selected_scenario_id: str | None
    assessments: tuple[ScenarioAssessment, ...]
    limiting_factors: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    override_scenario_id: str | None = None
    override_reason: str | None = None
    override_applied: bool = False

    @property
    def selected_assessment(self) -> ScenarioAssessment | None:
        if self.selected_scenario_id is None:
            return None
        return next(
            (item for item in self.assessments if item.scenario_id == self.selected_scenario_id),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "objective": self.objective.value,
            "input_fingerprint": self.input_fingerprint,
            "selected_scenario_id": self.selected_scenario_id,
            "assessments": [item.to_dict() for item in self.assessments],
            "limiting_factors": list(self.limiting_factors),
            "conditions": list(self.conditions),
            "override_scenario_id": self.override_scenario_id,
            "override_reason": self.override_reason,
            "override_applied": self.override_applied,
        }


def recommendation_input_fingerprint(
    scenarios: tuple[DesignScenario, ...] | list[DesignScenario],
    objective: RecommendationObjective | str,
    override_scenario_id: str | None = None,
    override_reason: str | None = None,
) -> str:
    """Hash candidate inputs and the explicit objective for stale-result checks."""

    payload = {
        "scenarios": [scenario.to_dict() for scenario in scenarios],
        "objective": _status(objective),
        "override_scenario_id": override_scenario_id,
        "override_reason": override_reason,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _assess_scenario(
    scenario: DesignScenario,
    objective: RecommendationObjective,
) -> ScenarioAssessment:
    statuses = {
        "match_quality": _status(scenario.match_status),
        "counterfactual_validation": _status(scenario.counterfactual_status),
        "power": _status(scenario.power_status),
        "media_delivery": _status(scenario.delivery_status),
        "effect_plausibility": _status(scenario.effect_status),
        "region_constraints": _status(scenario.region_constraints_status),
    }
    passes = {key: status in _PASS_STATUSES for key, status in statuses.items()}
    limiting: list[str] = []
    conditions: list[str] = []

    if not passes["match_quality"]:
        limiting.append(f"match quality status is {statuses['match_quality']}")
    if not passes["counterfactual_validation"]:
        limiting.append(
            f"counterfactual validation status is {statuses['counterfactual_validation']}"
        )
    if not passes["power"]:
        limiting.append(f"power status is {statuses['power']}")
    if not scenario.power_usable:
        passes["power"] = False
        limiting.append("power result is not usable for recommendation")
    if scenario.power_meets_target is not True:
        passes["power"] = False
        limiting.append("power does not meet the selected target")
    passes["media_delivery"] = statuses["media_delivery"] == "feasible"
    if not passes["media_delivery"]:
        limiting.append(f"media delivery status is {statuses['media_delivery']}")
    passes["effect_plausibility"] = statuses["effect_plausibility"] in {
        "evidence_backed",
        "conditional",
    }
    if statuses["effect_plausibility"] == "conditional" and scenario.effect_meets_mde is True:
        passes["effect_plausibility"] = True
        conditions.append("effect plausibility is conditional on the recorded evidence bridge")
    elif statuses["effect_plausibility"] not in {"evidence_backed"}:
        passes["effect_plausibility"] = False
        limiting.append(f"effect plausibility status is {statuses['effect_plausibility']}")
    if scenario.effect_meets_mde is not True:
        passes["effect_plausibility"] = False
        limiting.append("effect scenario does not meet the selected MDE")
    if not passes["region_constraints"]:
        limiting.append(f"region constraints status is {statuses['region_constraints']}")
    if scenario.duration_periods <= 0:
        limiting.append("duration must be positive")
    if objective is RecommendationObjective.LEAST_COST_QUALIFYING_DESIGN and scenario.cost is None:
        limiting.append("cost is required for the least-cost objective")

    limiting.extend(str(note) for note in scenario.notes)
    limiting = list(dict.fromkeys(limiting))
    conditional = not limiting and statuses["effect_plausibility"] == "conditional"
    full_gates_pass = not limiting and all(passes.values()) and not conditional
    return ScenarioAssessment(
        scenario_id=scenario.scenario_id,
        qualifies=full_gates_pass,
        conditional=conditional,
        gate_statuses=statuses,
        gate_passes=passes,
        limiting_factors=tuple(limiting),
        conditions=tuple(dict.fromkeys(conditions)),
        size_metric=scenario.size_metric,
        duration_periods=scenario.duration_periods,
        cost=scenario.cost,
    )


def _selection_key(
    item: tuple[int, ScenarioAssessment], objective: RecommendationObjective
) -> tuple[Any, ...]:
    index, assessment = item
    cost_key = float("inf") if assessment.cost is None else assessment.cost
    if objective is RecommendationObjective.LEAST_COST_QUALIFYING_DESIGN:
        return (cost_key, assessment.size_metric, assessment.duration_periods, index)
    return (assessment.size_metric, assessment.duration_periods, cost_key, index)


def assess_design_recommendation(
    scenarios: tuple[DesignScenario, ...] | list[DesignScenario],
    objective: RecommendationObjective | str,
    *,
    override_scenario_id: str | None = None,
    override_reason: str | None = None,
) -> RecommendationResult:
    """Compare complete designs under an explicit objective.

    A fully qualifying candidate is ``recommended``.  A candidate whose only
    non-failing uncertainty is a conditional effect bridge is ``conditional``.
    An override can select any candidate, but a non-qualifying override remains
    conditional and retains its limiting factors.
    """

    if not scenarios:
        raise ValueError("at least one design scenario is required")
    try:
        selected_objective = RecommendationObjective(objective)
    except ValueError as exc:
        raise ValueError(
            "objective must be 'smallest_qualifying_design' or 'least_cost_qualifying_design'"
        ) from exc
    identifiers = [scenario.scenario_id for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("scenario_id values must be unique")
    if override_scenario_id is not None and not str(override_scenario_id).strip():
        raise ValueError("override_scenario_id must not be empty")
    if override_scenario_id is not None and not (override_reason or "").strip():
        raise ValueError("override_reason is required when overriding a recommendation")

    assessments = tuple(_assess_scenario(scenario, selected_objective) for scenario in scenarios)
    full_candidates = [
        (index, item) for index, item in enumerate(assessments) if item.qualifies
    ]
    conditional_candidates = [
        (index, item) for index, item in enumerate(assessments) if item.conditional
    ]
    selected: ScenarioAssessment | None = None
    if full_candidates:
        selected = min(full_candidates, key=lambda item: _selection_key(item, selected_objective))[1]
    elif conditional_candidates:
        selected = min(
            conditional_candidates, key=lambda item: _selection_key(item, selected_objective)
        )[1]

    override_applied = override_scenario_id is not None
    if override_applied:
        selected = next(
            item for item in assessments if item.scenario_id == str(override_scenario_id).strip()
        ) if str(override_scenario_id).strip() in identifiers else None
        if selected is None:
            raise ValueError(f"override scenario {override_scenario_id!r} was not found")

    if selected is None:
        status = RecommendationStatus.NO_QUALIFYING_DESIGN
        limiting_factors = tuple(
            dict.fromkeys(
                f"{item.scenario_id}: {factor}"
                for item in assessments
                for factor in item.limiting_factors
            )
        )
        conditions: tuple[str, ...] = ()
    else:
        selected_is_full = selected.qualifies
        status = (
            RecommendationStatus.RECOMMENDED
            if selected_is_full
            else RecommendationStatus.CONDITIONAL
        )
        limiting_factors = selected.limiting_factors
        conditions = selected.conditions
        if override_applied:
            conditions = tuple(
                dict.fromkeys((*conditions, "analyst override applied; review the recorded reason"))
            )
    fingerprint = recommendation_input_fingerprint(
        tuple(scenarios), selected_objective, override_scenario_id, override_reason
    )
    return RecommendationResult(
        schema_version=RECOMMENDATION_SCHEMA_VERSION,
        status=status,
        objective=selected_objective,
        input_fingerprint=fingerprint,
        selected_scenario_id=selected.scenario_id if selected else None,
        assessments=assessments,
        limiting_factors=limiting_factors,
        conditions=conditions,
        override_scenario_id=(str(override_scenario_id).strip() if override_scenario_id else None),
        override_reason=(override_reason.strip() if override_reason else None),
        override_applied=override_applied,
    )


def recommendation_result_is_stale(
    result: RecommendationResult,
    scenarios: tuple[DesignScenario, ...] | list[DesignScenario],
    objective: RecommendationObjective | str,
    *,
    override_scenario_id: str | None = None,
    override_reason: str | None = None,
) -> bool:
    """Return whether candidate inputs, objective or override identity changed."""

    return result.input_fingerprint != recommendation_input_fingerprint(
        tuple(scenarios), objective, override_scenario_id, override_reason
    )
