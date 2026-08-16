"""Task-led navigation state for the target information architecture.

This module defines the target navigation model (see the UX overhaul
programme, section 6): an entry screen with three choices, a four-step
``Plan a new geo test`` journey, and an ``Analyse a completed geo test``
journey with no internal step navigation of its own (it always shows
Results, with an optional advanced-uncertainty toggle). PR2 wired this into
``geotestmatch.py`` in place of the former eight-tab navigation; PR4 merged
the validation/power steps and PR5 merged the media/effect-plausibility
steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class JourneyArea(Enum):
    """The three entry choices on the home screen."""

    ENTRY = "entry"
    PLAN = "plan"
    EVALUATE = "evaluate"


class PlanStep(Enum):
    """The sequential stages of ``Plan a new geo test``.

    PR4 merged the former ``VALIDATE_DESIGN``/``POWER_SIZING`` steps into one
    ``CHECK_DESIGN`` step (historical validation and statistical power are
    rendered together, though their underlying computations and statuses
    remain separate). PR5 similarly merged ``MEDIA_DELIVERY``/
    ``EFFECT_PLAUSIBILITY`` into one ``MEDIA_AND_IMPACT`` step.
    """

    REGIONS = "regions"
    CHECK_DESIGN = "check_design"
    MEDIA_AND_IMPACT = "media_and_impact"
    REVIEW = "review"


PLAN_STEP_ORDER: Final[tuple[PlanStep, ...]] = (
    PlanStep.REGIONS,
    PlanStep.CHECK_DESIGN,
    PlanStep.MEDIA_AND_IMPACT,
    PlanStep.REVIEW,
)

PLAN_STEP_TITLES: Final[dict[PlanStep, str]] = {
    PlanStep.REGIONS: "Choose regions",
    PlanStep.CHECK_DESIGN: "Check design",
    PlanStep.MEDIA_AND_IMPACT: "Media and expected impact",
    PlanStep.REVIEW: "Review and approve",
}


@dataclass(frozen=True)
class NavigationState:
    """The analyst's current position in the task-led shell.

    Immutable: every transition returns a new state rather than mutating in
    place, so it can be stored directly in ``st.session_state`` and compared
    safely across reruns.
    """

    area: JourneyArea = JourneyArea.ENTRY
    plan_step: PlanStep = PlanStep.REGIONS

    def with_area(self, area: JourneyArea) -> NavigationState:
        """Switch the active journey area, preserving the Plan journey's step position."""
        return NavigationState(area=area, plan_step=self.plan_step)

    def advance_plan(self) -> NavigationState:
        """Move to the next planning step, or stay put if already at the last step."""
        index = PLAN_STEP_ORDER.index(self.plan_step)
        if index + 1 >= len(PLAN_STEP_ORDER):
            return self
        return NavigationState(area=self.area, plan_step=PLAN_STEP_ORDER[index + 1])

    def retreat_plan(self) -> NavigationState:
        """Move to the previous planning step, or stay put if already at the first step."""
        index = PLAN_STEP_ORDER.index(self.plan_step)
        if index == 0:
            return self
        return NavigationState(area=self.area, plan_step=PLAN_STEP_ORDER[index - 1])
