"""Coverage for the target task-led navigation state model.

This exercises the model in isolation; ``tests/test_navigation_app.py``
covers how ``geotestmatch.py`` wires it into the running app.
"""

from __future__ import annotations

from geotestlab.ui.navigation import (
    PLAN_STEP_ORDER,
    PLAN_STEP_TITLES,
    JourneyArea,
    NavigationState,
    PlanStep,
)


def test_every_plan_step_has_a_title_and_an_order_position():
    assert set(PLAN_STEP_TITLES) == set(PlanStep)
    assert set(PLAN_STEP_ORDER) == set(PlanStep)


def test_default_state_starts_at_entry():
    state = NavigationState()
    assert state.area is JourneyArea.ENTRY
    assert state.plan_step is PlanStep.REGIONS


def test_advance_plan_moves_through_every_step_in_order():
    state = NavigationState(area=JourneyArea.PLAN)
    seen = [state.plan_step]
    for _ in range(len(PLAN_STEP_ORDER) - 1):
        state = state.advance_plan()
        seen.append(state.plan_step)
    assert tuple(seen) == PLAN_STEP_ORDER


def test_advance_plan_stops_at_last_step():
    state = NavigationState(area=JourneyArea.PLAN, plan_step=PLAN_STEP_ORDER[-1])
    assert state.advance_plan().plan_step == PLAN_STEP_ORDER[-1]


def test_retreat_plan_stops_at_first_step():
    state = NavigationState(area=JourneyArea.PLAN, plan_step=PLAN_STEP_ORDER[0])
    assert state.retreat_plan().plan_step == PLAN_STEP_ORDER[0]


def test_retreat_plan_moves_backward():
    state = NavigationState(area=JourneyArea.PLAN, plan_step=PlanStep.REVIEW)
    assert state.retreat_plan().plan_step == PlanStep.MEDIA_AND_IMPACT


def test_with_area_switches_area_and_preserves_plan_step():
    state = NavigationState(area=JourneyArea.PLAN, plan_step=PlanStep.CHECK_DESIGN)
    switched = state.with_area(JourneyArea.EVALUATE)
    assert switched.area is JourneyArea.EVALUATE
    assert switched.plan_step is PlanStep.CHECK_DESIGN


def test_navigation_state_transitions_are_immutable_and_hashable():
    state = NavigationState()
    advanced = state.advance_plan()
    assert state.plan_step is PlanStep.REGIONS
    assert advanced.plan_step is PlanStep.CHECK_DESIGN
    assert state != advanced
    assert hash(state) != hash(advanced)
