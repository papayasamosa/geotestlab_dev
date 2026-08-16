"""Coverage for the thin session-state wrapper around NavigationState.

Follows the ``monkeypatch.setattr(module.st, "session_state", {...})``
pattern already used in ``tests/test_power_ui.py``.
"""

from __future__ import annotations

import geotestlab.ui.state as state_mod
from geotestlab.ui.navigation import JourneyArea, NavigationState, PlanStep


def test_get_navigation_state_initialises_default_on_first_use(monkeypatch):
    session_state = {}
    monkeypatch.setattr(state_mod.st, "session_state", session_state)

    state = state_mod.get_navigation_state()

    assert state == NavigationState()
    assert session_state[state_mod._NAVIGATION_KEY] == NavigationState()


def test_get_navigation_state_returns_existing_state(monkeypatch):
    existing = NavigationState(area=JourneyArea.PLAN, plan_step=PlanStep.DESIGN)
    session_state = {state_mod._NAVIGATION_KEY: existing}
    monkeypatch.setattr(state_mod.st, "session_state", session_state)

    assert state_mod.get_navigation_state() is existing


def test_get_navigation_state_replaces_a_corrupted_value(monkeypatch):
    session_state = {state_mod._NAVIGATION_KEY: "not-a-navigation-state"}
    monkeypatch.setattr(state_mod.st, "session_state", session_state)

    state = state_mod.get_navigation_state()

    assert state == NavigationState()
    assert session_state[state_mod._NAVIGATION_KEY] == NavigationState()


def test_set_navigation_state_persists_the_given_state(monkeypatch):
    session_state = {}
    monkeypatch.setattr(state_mod.st, "session_state", session_state)
    new_state = NavigationState(area=JourneyArea.EVALUATE)

    state_mod.set_navigation_state(new_state)

    assert session_state[state_mod._NAVIGATION_KEY] is new_state
