"""Thin session-state wrapper for the task-led navigation shell.

Only the new :class:`~geotestlab.ui.navigation.NavigationState` lives behind
this wrapper for now. The existing ``geotestmatch.py`` session-state keys
(match results, validation results, experiment-record state, and so on) are
untouched until later PRs migrate individual pages into ``geotestlab/ui/``;
this module does not read or write any of them.
"""

from __future__ import annotations

import streamlit as st

from geotestlab.ui.navigation import NavigationState

_NAVIGATION_KEY = "ui_navigation_state"


def get_navigation_state() -> NavigationState:
    """Return the current navigation state, initialising it on first use."""
    state = st.session_state.get(_NAVIGATION_KEY)
    if not isinstance(state, NavigationState):
        state = NavigationState()
        st.session_state[_NAVIGATION_KEY] = state
    return state


def set_navigation_state(state: NavigationState) -> None:
    """Persist a new navigation state for the remainder of the session."""
    st.session_state[_NAVIGATION_KEY] = state
