"""Coverage for the target task-led navigation state model.

This exercises the model in isolation; ``tests/test_navigation_app.py``
covers how ``geotestmatch.py`` wires it into the running app.
"""

from __future__ import annotations

from geotestlab.ui.navigation import (
    EVALUATE_STEP_ORDER,
    EVALUATE_STEP_TITLES,
    PLAN_STEP_ORDER,
    PLAN_STEP_TITLES,
    EvaluateStep,
    JourneyArea,
    NavigationState,
    PlanStep,
)


def test_every_plan_step_has_a_title_and_an_order_position():
    assert set(PLAN_STEP_TITLES) == set(PlanStep)
    assert set(PLAN_STEP_ORDER) == set(PlanStep)


def test_every_evaluate_step_has_a_title_and_an_order_position():
    assert set(EVALUATE_STEP_TITLES) == set(EvaluateStep)
    assert set(EVALUATE_STEP_ORDER) == set(EvaluateStep)


def test_default_state_starts_at_entry():
    state = NavigationState()
    assert state.area is JourneyArea.ENTRY
    assert state.plan_step is PlanStep.REGIONS
    assert state.evaluate_step is EvaluateStep.SETUP


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
    assert state.retreat_plan().plan_step == PlanStep.EFFECT_PLAUSIBILITY


def test_advance_evaluate_moves_through_every_step_in_order():
    state = NavigationState(area=JourneyArea.EVALUATE)
    seen = [state.evaluate_step]
    for _ in range(len(EVALUATE_STEP_ORDER) - 1):
        state = state.advance_evaluate()
        seen.append(state.evaluate_step)
    assert tuple(seen) == EVALUATE_STEP_ORDER


def test_advance_evaluate_stops_at_last_step():
    state = NavigationState(area=JourneyArea.EVALUATE, evaluate_step=EVALUATE_STEP_ORDER[-1])
    assert state.advance_evaluate().evaluate_step == EVALUATE_STEP_ORDER[-1]


def test_retreat_evaluate_stops_at_first_step():
    state = NavigationState(area=JourneyArea.EVALUATE, evaluate_step=EVALUATE_STEP_ORDER[0])
    assert state.retreat_evaluate().evaluate_step == EVALUATE_STEP_ORDER[0]


def test_retreat_evaluate_moves_backward():
    state = NavigationState(area=JourneyArea.EVALUATE, evaluate_step=EvaluateStep.RESULTS)
    assert state.retreat_evaluate().evaluate_step == EvaluateStep.SETUP


def test_with_area_switches_area_and_preserves_step_positions():
    state = NavigationState(area=JourneyArea.PLAN, plan_step=PlanStep.VALIDATE_DESIGN)
    switched = state.with_area(JourneyArea.EVALUATE)
    assert switched.area is JourneyArea.EVALUATE
    assert switched.plan_step is PlanStep.VALIDATE_DESIGN
    assert switched.evaluate_step is EvaluateStep.SETUP


def test_navigation_state_transitions_are_immutable_and_hashable():
    state = NavigationState()
    advanced = state.advance_plan()
    assert state.plan_step is PlanStep.REGIONS
    assert advanced.plan_step is PlanStep.VALIDATE_DESIGN
    assert state != advanced
    assert hash(state) != hash(advanced)
