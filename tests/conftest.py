"""Shared fixtures for GeoTestLab tests."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from geotestlab.ui import JourneyArea, NavigationState, PlanStep

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def live_app():
    """Start the live Streamlit app once per module, already past the entry screen.

    Since PR2 the app opens on a task-led entry screen with no sidebar or
    analytical content (see ``geotestlab/ui/navigation.py``); this fixture
    pre-seeds navigation into the first Plan step (Region Matching), matching
    what every caller of this fixture expected to see before that entry
    screen existed. Tests that need a different step should seed their own
    ``AppTest`` via ``seed_plan_step``/``seed_evaluate`` instead of this fixture.

    Returns an ``AppTest`` instance with the app already executed.
    Use ``app.run()`` again only if widget interaction requires re-run.
    """
    app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
    seed_plan_step(app, PlanStep.REGIONS)
    app.run(timeout=180)
    return app


def seed_plan_step(app: AppTest, step: PlanStep) -> None:
    """Pre-seed navigation state so ``app.run()`` boots directly into a Plan step.

    Since PR2, the app opens on the task-led entry screen by default (no
    analytical content renders there). Call this before the first ``app.run()``
    so a test can reach a specific planning step (Region Matching, Validate
    Test Design, Power & Test Sizing, Media Delivery Feasibility, Effect
    Plausibility or Design Recommendation/Approve Design) without simulating
    the entry-screen and step-navigation button clicks.
    """
    app.session_state["ui_navigation_state"] = NavigationState(area=JourneyArea.PLAN, plan_step=step)


def seed_evaluate(app: AppTest, *, show_advanced_uncertainty: bool = False) -> None:
    """Pre-seed navigation state so ``app.run()`` boots directly into Evaluate results.

    ``show_advanced_uncertainty=True`` additionally reveals the Bayesian TBR
    content, which since PR2 only renders when the "Run advanced uncertainty
    analysis" toggle within the Results step is on.
    """
    app.session_state["ui_navigation_state"] = NavigationState(area=JourneyArea.EVALUATE)
    if show_advanced_uncertainty:
        app.session_state["_show_advanced_uncertainty"] = True
