"""User-facing UI foundation: label mappings, navigation state and reusable
Streamlit components for the task-led shell (see the UX overhaul programme,
``docs/product/`` planning notes and section 8's target package shape).

Domain and statistical logic never lives here; this package only translates
existing typed results from ``geotestlab/`` into analyst-facing presentation.
"""

from geotestlab.ui.labels import display_label, format_date_range, format_percent
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
from geotestlab.ui.state import get_navigation_state, set_navigation_state

__all__ = [
    "EVALUATE_STEP_ORDER",
    "EVALUATE_STEP_TITLES",
    "EvaluateStep",
    "JourneyArea",
    "NavigationState",
    "PLAN_STEP_ORDER",
    "PLAN_STEP_TITLES",
    "PlanStep",
    "display_label",
    "format_date_range",
    "format_percent",
    "get_navigation_state",
    "set_navigation_state",
]
