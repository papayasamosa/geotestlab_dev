"""Task-led navigation state for the target information architecture.

This module defines the target navigation model (see the UX overhaul
programme, section 6): an entry screen with three choices, a five-step
``Plan a new geo test`` journey and a two-step ``Analyse a completed geo
test`` journey. PR2 wired this into ``geotestmatch.py`` in place of the
former eight-tab navigation; PR4 merged the validation/power steps.
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
    remain separate). A later PR may similarly merge ``MEDIA_DELIVERY``/
    ``EFFECT_PLAUSIBILITY`` into one "Media and expected impact" step once
    that content is unified (see the UX overhaul programme, section 6.2/PR5).
    """

    REGIONS = "regions"
    CHECK_DESIGN = "check_design"
    MEDIA_DELIVERY = "media_delivery"
    EFFECT_PLAUSIBILITY = "effect_plausibility"
    REVIEW = "review"


class EvaluateStep(Enum):
    """The two sequential stages of ``Analyse a completed geo test``."""

    SETUP = "setup"
    RESULTS = "results"


PLAN_STEP_ORDER: Final[tuple[PlanStep, ...]] = (
    PlanStep.REGIONS,
    PlanStep.CHECK_DESIGN,
    PlanStep.MEDIA_DELIVERY,
    PlanStep.EFFECT_PLAUSIBILITY,
    PlanStep.REVIEW,
)

EVALUATE_STEP_ORDER: Final[tuple[EvaluateStep, ...]] = (
    EvaluateStep.SETUP,
    EvaluateStep.RESULTS,
)

PLAN_STEP_TITLES: Final[dict[PlanStep, str]] = {
    PlanStep.REGIONS: "Choose regions",
    PlanStep.CHECK_DESIGN: "Check design",
    PlanStep.MEDIA_DELIVERY: "Media plan",
    PlanStep.EFFECT_PLAUSIBILITY: "Expected impact",
    PlanStep.REVIEW: "Review and approve",
}

EVALUATE_STEP_TITLES: Final[dict[EvaluateStep, str]] = {
    EvaluateStep.SETUP: "Select design and data",
    EvaluateStep.RESULTS: "Results",
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
    evaluate_step: EvaluateStep = EvaluateStep.SETUP

    def with_area(self, area: JourneyArea) -> NavigationState:
        """Switch the active journey area, preserving both journeys' step positions."""
        return NavigationState(
            area=area, plan_step=self.plan_step, evaluate_step=self.evaluate_step
        )

    def advance_plan(self) -> NavigationState:
        """Move to the next planning step, or stay put if already at the last step."""
        index = PLAN_STEP_ORDER.index(self.plan_step)
        if index + 1 >= len(PLAN_STEP_ORDER):
            return self
        return NavigationState(
            area=self.area, plan_step=PLAN_STEP_ORDER[index + 1], evaluate_step=self.evaluate_step
        )

    def retreat_plan(self) -> NavigationState:
        """Move to the previous planning step, or stay put if already at the first step."""
        index = PLAN_STEP_ORDER.index(self.plan_step)
        if index == 0:
            return self
        return NavigationState(
            area=self.area, plan_step=PLAN_STEP_ORDER[index - 1], evaluate_step=self.evaluate_step
        )

    def advance_evaluate(self) -> NavigationState:
        """Move to the next evaluation step, or stay put if already at the last step."""
        index = EVALUATE_STEP_ORDER.index(self.evaluate_step)
        if index + 1 >= len(EVALUATE_STEP_ORDER):
            return self
        return NavigationState(
            area=self.area, plan_step=self.plan_step, evaluate_step=EVALUATE_STEP_ORDER[index + 1]
        )

    def retreat_evaluate(self) -> NavigationState:
        """Move to the previous evaluation step, or stay put if already at the first step."""
        index = EVALUATE_STEP_ORDER.index(self.evaluate_step)
        if index == 0:
            return self
        return NavigationState(
            area=self.area, plan_step=self.plan_step, evaluate_step=EVALUATE_STEP_ORDER[index - 1]
        )
