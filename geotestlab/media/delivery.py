"""Platform-profile delivery feasibility calculations.

This module assesses whether entered or forecast delivery inputs meet explicit
exposure thresholds. It does not consume statistical power results and never
converts delivery into an incremental KPI-effect claim.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from geotestlab.media.profiles import (
    InputProvenance,
    MediaPlan,
    MediaValue,
    PlatformProfile,
)

DELIVERY_CONTRACT_VERSION = "media-delivery/v1"


class DeliveryStatus(StrEnum):
    """Outcome of the delivery-only feasibility assessment."""

    FEASIBLE = "feasible"
    NOT_FEASIBLE = "not_feasible"
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DeliveryThresholds:
    """Minimum delivery requirements selected for the planned test."""

    min_impressions: float | None = None
    min_reach: float | None = None
    min_reach_percentage: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("min_impressions", self.min_impressions),
            ("min_reach", self.min_reach),
            ("min_reach_percentage", self.min_reach_percentage),
        ):
            if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.min_reach_percentage is not None and self.min_reach_percentage > 100:
            raise ValueError("min_reach_percentage cannot exceed 100")

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentMediaScope:
    """Make analytical exclusions distinct from ordinary media delivery."""

    excluded_from_experiment: tuple[str, ...] = ()
    ordinary_media_allowed_in_excluded_regions: bool = True

    def __post_init__(self) -> None:
        regions = tuple(
            sorted(
                {
                    str(region).strip()
                    for region in self.excluded_from_experiment
                    if str(region).strip()
                }
            )
        )
        object.__setattr__(self, "excluded_from_experiment", regions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "excluded_from_experiment": list(self.excluded_from_experiment),
            "ordinary_media_allowed_in_excluded_regions": (
                self.ordinary_media_allowed_in_excluded_regions
            ),
        }


@dataclass(frozen=True)
class DeliveryAssessment:
    """Auditable delivery result with status separate from statistical power."""

    delivery_contract_version: str
    profile_id: str
    status: DeliveryStatus
    input_fingerprint: str
    values: dict[str, MediaValue]
    thresholds: DeliveryThresholds
    scope: ExperimentMediaScope
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    calculated_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, provenance-preserving delivery export."""

        return {
            "delivery_contract_version": self.delivery_contract_version,
            "profile_id": self.profile_id,
            "status": self.status.value,
            "input_fingerprint": self.input_fingerprint,
            "values": {key: self.values[key].to_dict() for key in sorted(self.values)},
            "thresholds": self.thresholds.to_dict(),
            "scope": self.scope.to_dict(),
            "checks": self.checks,
            "calculated_fields": list(self.calculated_fields),
            "missing_fields": list(self.missing_fields),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def delivery_input_fingerprint(
    plan: MediaPlan,
    thresholds: DeliveryThresholds | None = None,
    scope: ExperimentMediaScope | None = None,
) -> str:
    """Hash the raw plan, thresholds and analytical scope for staleness checks."""

    payload = {
        "plan": plan.to_dict(),
        "thresholds": (thresholds or DeliveryThresholds()).to_dict(),
        "scope": (scope or ExperimentMediaScope()).to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _number(values: dict[str, MediaValue], key: str) -> float | None:
    value = values.get(key)
    if value is None or isinstance(value.value, bool):
        return None
    try:
        return float(value.value)
    except (TypeError, ValueError):
        return None


def _calculated(values: dict[str, MediaValue], key: str, result: float, notes: str) -> None:
    values[key] = MediaValue(
        value=float(result),
        provenance=InputProvenance.CALCULATED,
        source="GeoTestLab delivery calculation",
        notes=notes,
    )


def _pattern_total(values: dict[str, MediaValue]) -> float | None:
    pattern = values.get("weekly_budget_pattern")
    if pattern is None or not isinstance(pattern.value, Mapping):
        return None
    amounts = []
    for amount in pattern.value.values():
        if isinstance(amount, bool):
            return None
        try:
            numeric = float(amount)
        except (TypeError, ValueError):
            return None
        if numeric < 0:
            return None
        amounts.append(numeric)
    return sum(amounts) if amounts else None


def assess_media_delivery(
    plan: MediaPlan,
    thresholds: DeliveryThresholds | None = None,
    scope: ExperimentMediaScope | None = None,
    profile: PlatformProfile | None = None,
) -> DeliveryAssessment:
    """Assess delivery thresholds and calculate only legitimate derived fields."""

    selected_thresholds = thresholds or DeliveryThresholds()
    selected_scope = scope or ExperimentMediaScope()
    validation_errors = plan.validation_errors(profile)
    fingerprint = delivery_input_fingerprint(plan, selected_thresholds, selected_scope)
    values = dict(plan.values)
    blockers = list(validation_errors)
    warnings: list[str] = []
    calculated_fields: list[str] = []

    if not blockers:
        budget = _number(values, "total_budget")
        if budget is None:
            pattern_total = _pattern_total(values)
            if pattern_total is not None:
                _calculated(values, "total_budget", pattern_total, "sum of weekly_budget_pattern")
                calculated_fields.append("total_budget")

        budget = _number(values, "total_budget")
        cpm = _number(values, "cpm")
        impressions = _number(values, "impressions")
        if impressions is None and budget is not None and cpm is not None and cpm > 0:
            _calculated(values, "impressions", budget / cpm * 1000, "total_budget / cpm * 1,000")
            calculated_fields.append("impressions")

        impressions = _number(values, "impressions")
        frequency = _number(values, "frequency")
        reach = _number(values, "reach")
        if reach is None and impressions is not None and frequency is not None and frequency > 0:
            _calculated(values, "reach", impressions / frequency, "impressions / frequency")
            calculated_fields.append("reach")

        reach = _number(values, "reach")
        if frequency is None and impressions is not None and reach is not None and reach > 0:
            _calculated(values, "frequency", impressions / reach, "impressions / reach")
            calculated_fields.append("frequency")

        audience = _number(values, "eligible_audience")
        reach_percentage = _number(values, "reach_percentage")
        if reach_percentage is None and reach is not None and audience is not None and audience > 0:
            _calculated(
                values,
                "reach_percentage",
                reach / audience * 100,
                "reach / eligible_audience * 100",
            )
            calculated_fields.append("reach_percentage")

        reach_percentage = _number(values, "reach_percentage")
        if reach_percentage is not None and reach_percentage > 100:
            blockers.append("reach_percentage cannot exceed 100%")
        if frequency is not None and frequency <= 0:
            blockers.append("frequency must be greater than zero")

    missing_fields: list[str] = []
    if not _number(values, "impressions"):
        missing_fields.append("impressions (or total budget plus CPM)")
    if selected_thresholds.min_reach is not None and not _number(values, "reach"):
        missing_fields.append("reach (or impressions plus frequency)")
    if selected_thresholds.min_reach_percentage is not None and not _number(
        values, "reach_percentage"
    ):
        missing_fields.append("reach percentage (or reach plus eligible audience)")
    if selected_scope.excluded_from_experiment:
        warnings.append(
            "Excluded geographies are outside the analytical test/control scope; ordinary media "
            f"is {'allowed' if selected_scope.ordinary_media_allowed_in_excluded_regions else 'not allowed'} "
            "there according to the explicit scope setting."
        )

    for key in ("total_budget", "cpm", "impressions", "reach"):
        media_value = values.get(key)
        if media_value and media_value.provenance == InputProvenance.SUPPLIED_FORECAST:
            if not media_value.source:
                warnings.append(f"{key} is a supplied forecast without a recorded source")
            if not media_value.source_date:
                warnings.append(f"{key} is a supplied forecast without a recorded source date")

    for key, label in (
        ("existing_activity_in_control", "existing activity in control"),
        ("spillover_contamination", "spillover or contamination"),
    ):
        media_value = values.get(key)
        if media_value and str(media_value.value).strip().lower() not in {
            "",
            "no",
            "none",
            "unknown",
        }:
            warnings.append(f"{label} is recorded and should be reviewed separately from delivery")

    checks: dict[str, dict[str, Any]] = {}
    for key, minimum in (
        ("impressions", selected_thresholds.min_impressions),
        ("reach", selected_thresholds.min_reach),
        ("reach_percentage", selected_thresholds.min_reach_percentage),
    ):
        if minimum is None:
            continue
        observed = _number(values, key)
        passes = observed is not None and observed >= minimum
        checks[key] = {
            "observed": observed,
            "minimum": float(minimum),
            "passes": passes,
            "provenance": values[key].provenance.value if key in values else None,
        }

    failed_checks = [key for key, check in checks.items() if not check["passes"]]
    if failed_checks:
        blockers.extend(f"{key} is below its minimum delivery threshold" for key in failed_checks)

    if blockers and validation_errors:
        status = DeliveryStatus.BLOCKED
    elif blockers:
        status = DeliveryStatus.NOT_FEASIBLE if failed_checks else DeliveryStatus.BLOCKED
    elif missing_fields:
        status = DeliveryStatus.INCOMPLETE
    else:
        status = DeliveryStatus.FEASIBLE

    return DeliveryAssessment(
        delivery_contract_version=DELIVERY_CONTRACT_VERSION,
        profile_id=plan.profile_id,
        status=status,
        input_fingerprint=fingerprint,
        values=values,
        thresholds=selected_thresholds,
        scope=selected_scope,
        checks=checks,
        calculated_fields=tuple(calculated_fields),
        missing_fields=tuple(missing_fields),
        blockers=tuple(blockers),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def delivery_result_is_stale(
    result: DeliveryAssessment,
    plan: MediaPlan,
    thresholds: DeliveryThresholds | None = None,
    scope: ExperimentMediaScope | None = None,
) -> bool:
    """Return whether raw media inputs, thresholds or analytical scope changed."""

    return result.input_fingerprint != delivery_input_fingerprint(plan, thresholds, scope)
