"""User-facing UI foundation: label mappings, navigation state and reusable
Streamlit components for the task-led shell (see the UX overhaul programme,
``docs/product/`` planning notes and section 8's target package shape).

Domain and statistical logic never lives here; this package only translates
existing typed results from ``geotestlab/`` into analyst-facing presentation.
"""

from geotestlab.ui.labels import display_label
from geotestlab.ui.navigation import (
    PLAN_STEP_ORDER,
    PLAN_STEP_TITLES,
    JourneyArea,
    NavigationState,
    PlanStep,
)
from geotestlab.ui.state import get_navigation_state, set_navigation_state

__all__ = [
    "JourneyArea",
    "NavigationState",
    "PLAN_STEP_ORDER",
    "PLAN_STEP_TITLES",
    "PlanStep",
    "display_label",
    "get_navigation_state",
    "set_navigation_state",
]
