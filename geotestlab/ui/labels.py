"""Central mapping from internal enum/status strings to analyst-facing labels.

Internal statuses, enum values and implementation vocabulary must never reach
the analyst as raw text (see the UX overhaul programme, sections 5.6 and 12).
This module is the single source of truth for that translation.

Each label table is scoped to one internal vocabulary (``kind``) rather than
merged into one flat namespace, because the same raw string can mean
different things in different domains (for example ``"incomplete"`` means
"missing delivery inputs" for :class:`~geotestlab.media.delivery.DeliveryStatus`
but "upstream stage not evaluated yet" for
:class:`~geotestlab.recommendation.recommendation.RecommendationStatus`).
``tests/test_ui_labels.py`` walks every tracked enum so a new member without a
label fails loudly instead of silently leaking into the UI.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Final

# --- Workflow stage status (geotestlab/experiment/stages.py: STAGE_STATUSES) ---
STAGE_STATUS_LABELS: Final[dict[str, str]] = {
    "not_started": "Not started",
    "planned": "Planned",
    "in_progress": "In progress",
    "completed": "Done",
    "stale": "Inputs changed",
    "not_applicable": "Not applicable",
}

# --- Effect direction (geotestlab/effect/plausibility.py: _EFFECT_DIRECTIONS) ---
EFFECT_DIRECTION_LABELS: Final[dict[str, str]] = {
    "one_sided_positive": "Increase",
    "one_sided_negative": "Decrease",
    "two_sided": "Either direction",
}

# --- Effect evidence type (geotestlab/effect/plausibility.py: EvidenceType) ---
EVIDENCE_TYPE_LABELS: Final[dict[str, str]] = {
    "prior_same_market_platform_geo_test": "Prior test, same market & platform",
    "comparable_market_test": "Prior test, comparable market",
    "mmm": "Calibrated MMM estimate",
    "incremental_cpa": "Historical incremental CPA",
    "incremental_cps": "Historical incremental CPS",
    "platform_lift_forecast": "Platform or agency lift forecast",
    "analyst_assumption": "Analyst assumption",
}

# --- Effect evidence quality (geotestlab/effect/plausibility.py: EvidenceQuality) ---
EVIDENCE_QUALITY_LABELS: Final[dict[str, str]] = {
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "unknown": "Unknown",
}

# --- Effect plausibility status (geotestlab/effect/plausibility.py) ---
EFFECT_PLAUSIBILITY_STATUS_LABELS: Final[dict[str, str]] = {
    "unknown": "Not checked yet",
    "conditional": "Conditional",
    "evidence_backed": "Evidence-backed",
    "blocked": "Not suitable",
}

# --- Media delivery status (geotestlab/media/delivery.py: DeliveryStatus) ---
DELIVERY_STATUS_LABELS: Final[dict[str, str]] = {
    "feasible": "Meets thresholds",
    "not_feasible": "Not suitable",
    "incomplete": "Missing information",
    "blocked": "Not suitable",
}

# --- Media-plan value provenance (geotestlab/media/profiles.py: InputProvenance) ---
INPUT_PROVENANCE_LABELS: Final[dict[str, str]] = {
    "supplied_forecast": "Supplied forecast",
    "calculated": "Calculated",
    "historical_observed": "Observed history",
    "analyst_assumption": "Analyst assumption",
}

# --- Recommendation objective (geotestlab/recommendation/recommendation.py) ---
RECOMMENDATION_OBJECTIVE_LABELS: Final[dict[str, str]] = {
    "smallest_qualifying_design": "Smallest viable design",
    "least_cost_qualifying_design": "Least-cost viable design",
}

# --- Recommendation status (geotestlab/recommendation/recommendation.py) ---
RECOMMENDATION_STATUS_LABELS: Final[dict[str, str]] = {
    "recommended": "Recommended",
    "conditional": "Conditional",
    "no_qualifying_design": "No viable design",
    "incomplete": "Not checked yet",
}

# --- Market-size measure (geotestlab/data/models.py: MarketSizeMeasure) ---
MARKET_SIZE_MEASURE_LABELS: Final[dict[str, str]] = {
    "historical_kpi_volume": "Historical KPI volume",
    "population": "Population",
    "custom_weight": "Custom weight",
}

# --- Counterfactual fit method (geotestlab/power/methods.py) ---
FIT_METHOD_LABELS: Final[dict[str, str]] = {
    "ols": "Automatic (OLS)",
    "elastic_net": "Elastic Net",
    "lasso": "LASSO",
    "constant_mean": "Automatic (fallback)",
}

# --- Generic gate status (geotestlab/recommendation/ui.py: per-candidate
# match/counterfactual/power/region-constraints gates). These are plain
# strings, not a formal enum — the recommendation layer reuses a small shared
# pass/fail/not-yet vocabulary across gates that don't each have their own
# typed status (unlike delivery_status/effect_plausibility_status, which ARE
# backed by real enums and use their own dedicated kind above). Migrated from
# the former unused ``_STATUS_OPTIONS`` tuple in that module.
GENERIC_GATE_STATUS_LABELS: Final[dict[str, str]] = {
    "not_evaluated": "Not checked yet",
    "pass": "Pass",
    "supported": "Ready to use",
    "credible": "Credible",
    "valid": "Valid",
    "incomplete": "Missing information",
    "blocked": "Not suitable",
    "not_feasible": "Not suitable",
    "stale": "Inputs changed",
}

# Every internal vocabulary this module knows how to translate, keyed by an
# explicit ``kind`` name so callers state which domain a raw value belongs to
# instead of relying on a single ambiguous namespace.
_LABEL_REGISTRY: Final[dict[str, dict[str, str]]] = {
    "stage_status": STAGE_STATUS_LABELS,
    "effect_direction": EFFECT_DIRECTION_LABELS,
    "evidence_type": EVIDENCE_TYPE_LABELS,
    "evidence_quality": EVIDENCE_QUALITY_LABELS,
    "effect_plausibility_status": EFFECT_PLAUSIBILITY_STATUS_LABELS,
    "delivery_status": DELIVERY_STATUS_LABELS,
    "input_provenance": INPUT_PROVENANCE_LABELS,
    "recommendation_objective": RECOMMENDATION_OBJECTIVE_LABELS,
    "recommendation_status": RECOMMENDATION_STATUS_LABELS,
    "market_size_measure": MARKET_SIZE_MEASURE_LABELS,
    "fit_method": FIT_METHOD_LABELS,
    "generic_gate_status": GENERIC_GATE_STATUS_LABELS,
}


def display_label(kind: str, value: object, *, default: str | None = None) -> str:
    """Translate an internal enum/status value into an analyst-facing label.

    ``kind`` selects which internal vocabulary ``value`` belongs to (one of
    the keys in ``_LABEL_REGISTRY``, matching a module in ``geotestlab/``).
    ``value`` may be a ``StrEnum`` member, a plain string, or ``None``.

    Falls back to ``default`` (or a humanised version of the raw value) when
    the value is not a recognised member of that vocabulary, so a rendering
    call never crashes on an unexpected value. ``tests/test_ui_labels.py``
    asserts every member of every tracked enum has an explicit mapping, so
    that fallback should never be exercised for a real status in practice.
    """
    if kind not in _LABEL_REGISTRY:
        raise KeyError(f"Unknown label kind: {kind!r}")
    if value is None:
        return default if default is not None else "Not set"
    key = value.value if isinstance(value, Enum) else str(value)
    labels = _LABEL_REGISTRY[kind]
    if key in labels:
        return labels[key]
    if default is not None:
        return default
    return key.replace("_", " ").strip().capitalize()


def format_percent(value: float | None, *, decimals: int = 1) -> str:
    """Format a fraction (e.g. ``0.052``) as a percentage string (``"5.2%"``)."""
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def format_date_range(start: date | datetime | None, end: date | datetime | None) -> str:
    """Format a date range consistently, e.g. ``"05 Jan 2025 – 12 Mar 2025"``."""
    if start is None or end is None:
        return "—"
    return f"{start:%d %b %Y} – {end:%d %b %Y}"
