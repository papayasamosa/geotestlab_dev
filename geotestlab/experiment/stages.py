"""Workflow stages and explicit stage statuses for an experiment record.

The product model keeps the following statuses separate (never collapsed into a
single unexplained score): match quality, counterfactual validation, statistical
power, media delivery, effect plausibility, observed impact.
"""

from __future__ import annotations

# The six product-level workflow stages, in workflow order.
STAGE_KEYS = (
    "match_quality",
    "counterfactual_validation",
    "statistical_power",
    "media_delivery",
    "effect_plausibility",
    "observed_impact",
)

STAGE_LABELS = {
    "match_quality": "Match quality",
    "counterfactual_validation": "Counterfactual validation",
    "statistical_power": "Statistical power",
    "media_delivery": "Media delivery",
    "effect_plausibility": "Effect plausibility",
    "observed_impact": "Observed impact",
}

# Explicit stage statuses.
#   not_started    — no result exists for this stage yet;
#   planned        — a future/planned stage (power, delivery, plausibility);
#   in_progress    — work is in progress;
#   completed      — a result exists and is current (not stale);
#   stale          — a result exists but the underlying inputs changed;
#   not_applicable — not applicable for this workflow.
STAGE_STATUSES = (
    "not_started",
    "planned",
    "in_progress",
    "completed",
    "stale",
    "not_applicable",
)

# Stages that are part of the current product but only planned/future.
_PLANNED_STAGES = ("statistical_power", "media_delivery", "effect_plausibility")


def default_stage_status() -> dict:
    """Initial status per stage: planned for future stages, not_started otherwise."""
    return {key: ("planned" if key in _PLANNED_STAGES else "not_started") for key in STAGE_KEYS}


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)
