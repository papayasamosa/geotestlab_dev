"""Task-led navigation state for the target information architecture.

This module defines the target navigation model (see the UX overhaul
programme, section 6): an entry screen with three choices, a five-step
``Plan a new geo test`` journey and a two-step ``Analyse a completed geo
test`` journey.

PR1 introduces this model only. The existing eight-tab navigation in
``geotestmatch.py`` keeps rendering unchanged until a later PR wires the new
shell in, so nothing here is imported by the running application yet.
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
    """The five sequential stages of ``Plan a new geo test``."""

    SETUP = "setup"
    REGIONS = "regions"
    DESIGN = "design"
    MEDIA_AND_IMPACT = "media_and_impact"
    REVIEW = "review"


class EvaluateStep(Enum):
    """The two sequential stages of ``Analyse a completed geo test``."""

    SETUP = "setup"
    RESULTS = "results"


PLAN_STEP_ORDER: Final[tuple[PlanStep, ...]] = (
    PlanStep.SETUP,
    PlanStep.REGIONS,
    PlanStep.DESIGN,
    PlanStep.MEDIA_AND_IMPACT,
    PlanStep.REVIEW,
)

EVALUATE_STEP_ORDER: Final[tuple[EvaluateStep, ...]] = (
    EvaluateStep.SETUP,
    EvaluateStep.RESULTS,
)

PLAN_STEP_TITLES: Final[dict[PlanStep, str]] = {
    PlanStep.SETUP: "Test setup",
    PlanStep.REGIONS: "Choose regions",
    PlanStep.DESIGN: "Check design",
    PlanStep.MEDIA_AND_IMPACT: "Media and expected impact",
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
    plan_step: PlanStep = PlanStep.SETUP
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
