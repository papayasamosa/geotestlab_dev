"""Evidence-aware effect plausibility and MDE comparison.

This module turns explicit effectiveness evidence into low/central/high uplift
scenarios. It never derives incremental KPI effect from spend, reach or
frequency alone and never produces the integrated design recommendation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

EFFECT_PLAUSIBILITY_SCHEMA_VERSION = "effect-plausibility/v1"


class EvidenceType(StrEnum):
    """Permitted evidence bridges for an expected KPI effect."""

    PRIOR_SAME_MARKET_PLATFORM_GEO_TEST = "prior_same_market_platform_geo_test"
    COMPARABLE_MARKET_TEST = "comparable_market_test"
    MMM = "mmm"
    INCREMENTAL_CPA = "incremental_cpa"
    INCREMENTAL_CPS = "incremental_cps"
    PLATFORM_LIFT_FORECAST = "platform_lift_forecast"
    ANALYST_ASSUMPTION = "analyst_assumption"


class EvidenceQuality(StrEnum):
    """Analyst assessment of evidence relevance and reliability."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class EffectPlausibilityStatus(StrEnum):
    """Status of the evidence bridge, not a final experiment recommendation."""

    UNKNOWN = "unknown"
    CONDITIONAL = "conditional"
    EVIDENCE_BACKED = "evidence_backed"
    BLOCKED = "blocked"


_SCENARIO_LABELS = ("low", "central", "high")
_EFFECT_DIRECTIONS = ("one_sided_positive", "one_sided_negative", "two_sided")


@dataclass(frozen=True)
class EffectScenario:
    """One expected relative KPI-uplift scenario, expressed in percentage points."""

    label: str
    expected_uplift_pct: float
    uncertainty_note: str = ""

    def __post_init__(self) -> None:
        if self.label not in _SCENARIO_LABELS:
            raise ValueError(f"scenario label must be one of {_SCENARIO_LABELS}")
        if not math.isfinite(float(self.expected_uplift_pct)):
            raise ValueError("expected_uplift_pct must be finite")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EffectEvidence:
    """An explicit evidence source and its low/central/high uplift bridge."""

    evidence_type: EvidenceType | str
    quality: EvidenceQuality | str
    source: str
    scenarios: tuple[EffectScenario, ...]
    source_date: str | None = None
    adjusted: bool = False
    central_approved: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        try:
            evidence_type = EvidenceType(self.evidence_type)
            quality = EvidenceQuality(self.quality)
        except ValueError as exc:
            raise ValueError("unknown evidence type or quality") from exc
        object.__setattr__(self, "evidence_type", evidence_type)
        object.__setattr__(self, "quality", quality)
        if not self.source.strip():
            raise ValueError("evidence source must not be empty")
        if self.source_date:
            try:
                datetime.fromisoformat(self.source_date.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("source_date must be a valid ISO date or datetime string") from exc
        labels = tuple(scenario.label for scenario in self.scenarios)
        if labels != _SCENARIO_LABELS:
            raise ValueError(f"scenarios must be ordered exactly as {_SCENARIO_LABELS}")
        effects = tuple(float(scenario.expected_uplift_pct) for scenario in self.scenarios)
        if not effects[0] <= effects[1] <= effects[2]:
            raise ValueError("scenario uplift values must be ordered low <= central <= high")

    def to_dict(self) -> dict[str, Any]:
        """Return evidence with source, quality and adjustment state preserved."""

        return {
            "evidence_type": self.evidence_type.value,
            "quality": self.quality.value,
            "source": self.source,
            "source_date": self.source_date,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "adjusted": self.adjusted,
            "central_approved": self.central_approved,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EffectComparison:
    """Comparison of one expected uplift scenario with the supplied MDE."""

    label: str
    expected_uplift_pct: float
    mde_pct: float | None
    meets_mde: bool | None
    margin_to_mde_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EffectPlausibilityResult:
    """Auditable effect bridge; it is not a combined delivery/power score."""

    schema_version: str
    status: EffectPlausibilityStatus
    input_fingerprint: str
    evidence: EffectEvidence | None
    mde_pct: float | None
    effect_direction: str
    comparisons: tuple[EffectComparison, ...]
    delivery_status: str | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "input_fingerprint": self.input_fingerprint,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "mde_pct": self.mde_pct,
            "effect_direction": self.effect_direction,
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "delivery_status": self.delivery_status,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def effect_input_fingerprint(
    evidence: EffectEvidence | None,
    mde_pct: float | None,
    effect_direction: str = "two_sided",
    delivery_status: str | None = None,
    delivery_fingerprint: str | None = None,
) -> str:
    """Hash evidence, MDE and delivery identity without collapsing their meanings."""

    payload = {
        "evidence": evidence.to_dict() if evidence else None,
        "mde_pct": mde_pct,
        "effect_direction": effect_direction,
        "delivery_status": delivery_status,
        "delivery_fingerprint": delivery_fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def assess_effect_plausibility(
    evidence: EffectEvidence | None,
    mde_pct: float | None = None,
    effect_direction: str = "two_sided",
    delivery_status: str | None = None,
    delivery_fingerprint: str | None = None,
) -> EffectPlausibilityResult:
    """Assess an explicit evidence bridge and compare scenarios with MDE."""

    if mde_pct is not None and (not math.isfinite(float(mde_pct)) or float(mde_pct) < 0):
        raise ValueError("mde_pct must be a finite non-negative number")
    if effect_direction not in _EFFECT_DIRECTIONS:
        raise ValueError(f"effect_direction must be one of {_EFFECT_DIRECTIONS}")
    fingerprint = effect_input_fingerprint(
        evidence, mde_pct, effect_direction, delivery_status, delivery_fingerprint
    )
    if evidence is None:
        return EffectPlausibilityResult(
            schema_version=EFFECT_PLAUSIBILITY_SCHEMA_VERSION,
            status=EffectPlausibilityStatus.UNKNOWN,
            input_fingerprint=fingerprint,
            evidence=None,
            mde_pct=mde_pct,
            effect_direction=effect_direction,
            comparisons=(),
            delivery_status=delivery_status,
            warnings=(
                "No effectiveness bridge was supplied; effect plausibility is unknown. "
                "Statistical power and delivery remain separate outputs.",
            ),
        )

    blockers: list[str] = []
    warnings: list[str] = []
    if evidence.adjusted and not evidence.central_approved:
        blockers.append(
            "Adjusted or outlier-excluded evidence cannot be used as the central scenario "
            "without explicit approval; retain it as a sensitivity scenario instead."
        )
    elif evidence.adjusted:
        warnings.append(
            "The central scenario uses an adjusted or outlier-excluded estimate with explicit approval."
        )
    if evidence.evidence_type in (EvidenceType.INCREMENTAL_CPA, EvidenceType.INCREMENTAL_CPS):
        warnings.append(
            "Incremental CPA/CPS is an assumption bridge to KPI uplift; it does not by itself "
            "identify an incremental KPI effect."
        )
    if evidence.quality is EvidenceQuality.UNKNOWN:
        warnings.append("Evidence quality is unknown; treat the bridge as conditional.")
    if not evidence.source_date:
        warnings.append("Evidence source date is not recorded.")
    if delivery_status:
        warnings.append(
            f"Delivery status is recorded separately as {delivery_status!r}; it is not combined "
            "with effect plausibility."
        )

    def effect_distance(effect: float) -> float:
        if effect_direction == "one_sided_positive":
            return effect
        if effect_direction == "one_sided_negative":
            return -effect
        return abs(effect)

    comparisons = tuple(
        EffectComparison(
            label=scenario.label,
            expected_uplift_pct=scenario.expected_uplift_pct,
            mde_pct=mde_pct,
            meets_mde=(
                effect_distance(scenario.expected_uplift_pct) >= mde_pct
                if mde_pct is not None
                else None
            ),
            margin_to_mde_pct=(
                effect_distance(scenario.expected_uplift_pct) - mde_pct
                if mde_pct is not None
                else None
            ),
        )
        for scenario in evidence.scenarios
    )
    status = (
        EffectPlausibilityStatus.BLOCKED
        if blockers
        else EffectPlausibilityStatus.CONDITIONAL
        if evidence.evidence_type is EvidenceType.ANALYST_ASSUMPTION
        or evidence.quality is EvidenceQuality.UNKNOWN
        else EffectPlausibilityStatus.EVIDENCE_BACKED
    )
    return EffectPlausibilityResult(
        schema_version=EFFECT_PLAUSIBILITY_SCHEMA_VERSION,
        status=status,
        input_fingerprint=fingerprint,
        evidence=evidence,
        mde_pct=mde_pct,
        effect_direction=effect_direction,
        comparisons=comparisons,
        delivery_status=delivery_status,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def effect_result_is_stale(
    result: EffectPlausibilityResult,
    evidence: EffectEvidence | None,
    mde_pct: float | None,
    effect_direction: str = "two_sided",
    delivery_status: str | None = None,
    delivery_fingerprint: str | None = None,
) -> bool:
    """Return whether evidence, MDE or referenced delivery identity changed."""

    return result.input_fingerprint != effect_input_fingerprint(
        evidence, mde_pct, effect_direction, delivery_status, delivery_fingerprint
    )
