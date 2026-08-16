"""AppTest coverage for the task-led navigation shell (PR2).

Covers the entry screen, the Plan a new geo test step navigator (Next/Back/
jump-to-step, all state-preserving), the Analyse a completed geo test
journey and its advanced-uncertainty toggle, and the Open a saved experiment
entry action. Individual step content is covered by the tests that exercise
that step directly (``test_power_ui_app.py``, ``test_data_quality.py``, ...);
this file only covers the navigation chrome itself.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from geotestlab.ui import EvaluateStep, JourneyArea, NavigationState, PlanStep
from tests.conftest import seed_evaluate, seed_plan_step
from tests.fixtures.live_scenarios import RUN_TIMEOUT

APP_PATH = str(Path(__file__).resolve().parent.parent / "geotestmatch.py")

EXPECTED_PLAN_STEP_LABELS = [
    "Choose regions",
    "Check design quality",
    "Can we detect the effect?",
    "Media plan",
    "Expected impact",
    "Review and approve",
]


def _entry_app() -> AppTest:
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)
    return app


def test_entry_screen_shows_exactly_three_choices_and_nothing_else():
    app = _entry_app()

    assert not app.exception
    assert [s.value for s in app.subheader] == ["What would you like to do?"]
    button_labels = [b.label for b in app.button]
    assert "📝 Plan a new geo test" in button_labels
    assert "📊 Analyse a completed geo test" in button_labels
    assert "📂 Open a saved experiment" in button_labels
    # No model settings, workflow status or sidebar content on the entry screen.
    assert len(app.sidebar.selectbox) == 0
    assert len(app.sidebar.radio) == 0
    assert not any("Workflow status" == s.value for s in app.subheader)


def test_plan_button_reaches_region_matching_with_sidebar_and_step_radio():
    app = _entry_app()
    plan_btn = next(b for b in app.button if "Plan a new geo test" in (b.label or ""))
    plan_btn.click().run(timeout=RUN_TIMEOUT)

    assert not app.exception
    step_radio = next(r for r in app.radio if r.label == "Step")
    assert list(step_radio.options) == EXPECTED_PLAN_STEP_LABELS
    assert step_radio.value == "Choose regions"
    assert any(s.value == "🧩 MATCHING SETUP" for s in app.subheader)
    # The sidebar (matching method/geography setup) is visible past the entry screen.
    assert any(r.label == "Matching method" for r in app.sidebar.radio)


def test_next_and_back_buttons_move_through_every_plan_step_in_order():
    app = _entry_app()
    seed_plan_step(app, PlanStep.REGIONS)
    app.run(timeout=RUN_TIMEOUT)

    visited = [next(r for r in app.radio if r.label == "Step").value]
    for _ in range(len(EXPECTED_PLAN_STEP_LABELS) - 1):
        next_btn = next(b for b in app.button if b.label and "Next" in b.label)
        next_btn.click().run(timeout=RUN_TIMEOUT)
        assert not app.exception
        visited.append(next(r for r in app.radio if r.label == "Step").value)
    assert visited == EXPECTED_PLAN_STEP_LABELS

    # At the last step, Next is disabled and does not move further.
    next_btn = next(b for b in app.button if b.label and "Next" in b.label)
    assert next_btn.disabled is True

    back_btn = next(b for b in app.button if b.label and "Back" in b.label)
    back_btn.click().run(timeout=RUN_TIMEOUT)
    assert not app.exception
    assert next(r for r in app.radio if r.label == "Step").value == "Expected impact"


def test_jumping_directly_to_a_step_via_the_radio_updates_content():
    app = _entry_app()
    seed_plan_step(app, PlanStep.REGIONS)
    app.run(timeout=RUN_TIMEOUT)

    step_radio = next(r for r in app.radio if r.label == "Step")
    step_radio.set_value("Media plan")
    app.run(timeout=RUN_TIMEOUT)

    assert not app.exception
    assert any(s.value == "📣 Media Delivery Feasibility" for s in app.subheader)
    assert not any(s.value == "🧩 MATCHING SETUP" for s in app.subheader)


def test_start_over_returns_to_entry_screen_and_resets_step():
    app = _entry_app()
    seed_plan_step(app, PlanStep.REVIEW)
    app.run(timeout=RUN_TIMEOUT)

    home_btn = next(b for b in app.button if b.label and "Start over" in b.label)
    home_btn.click().run(timeout=RUN_TIMEOUT)

    assert not app.exception
    assert [s.value for s in app.subheader] == ["What would you like to do?"]

    # Re-entering Plan starts from the first step again, not the abandoned one.
    plan_btn = next(b for b in app.button if "Plan a new geo test" in (b.label or ""))
    plan_btn.click().run(timeout=RUN_TIMEOUT)
    assert next(r for r in app.radio if r.label == "Step").value == "Choose regions"


def test_evaluate_journey_shows_results_without_bayesian_by_default():
    app = _entry_app()
    seed_evaluate(app)
    app.run(timeout=RUN_TIMEOUT)

    assert not app.exception
    assert any(s.value == "📊 Measure Test Impact" for s in app.subheader)
    assert not any("Bayesian" in s.value for s in app.subheader)
    toggle_labels = [b.label for b in app.button if b.label and "uncertainty" in b.label]
    assert toggle_labels == ["🔬 Run advanced uncertainty analysis"]


def test_advanced_uncertainty_toggle_reveals_and_hides_bayesian_content():
    app = _entry_app()
    seed_evaluate(app)
    app.run(timeout=RUN_TIMEOUT)

    toggle_btn = next(b for b in app.button if b.label and "uncertainty" in b.label)
    toggle_btn.click().run(timeout=RUN_TIMEOUT)

    assert not app.exception
    assert any("Bayesian Time-Based Regression" in s.value for s in app.subheader)
    hide_btn = next(b for b in app.button if b.label and "Hide advanced uncertainty" in b.label)

    hide_btn.click().run(timeout=RUN_TIMEOUT)
    assert not any("Bayesian" in s.value for s in app.subheader)


def test_open_saved_experiment_shows_uploader_on_the_entry_screen():
    app = _entry_app()
    open_btn = next(b for b in app.button if "Open a saved experiment" in (b.label or ""))
    open_btn.click().run(timeout=RUN_TIMEOUT)

    assert not app.exception
    assert [s.value for s in app.subheader] == ["What would you like to do?"]
    assert any(f.key == "entry_load_experiment_record_uploader" for f in app.file_uploader), (
        "Experiment-record uploader should be reachable directly from the entry screen"
    )


def test_navigation_state_round_trips_through_session_state():
    app = _entry_app()
    seed_plan_step(app, PlanStep.POWER_SIZING)
    app.run(timeout=RUN_TIMEOUT)

    state = app.session_state["ui_navigation_state"]
    assert state == NavigationState(area=JourneyArea.PLAN, plan_step=PlanStep.POWER_SIZING)

    seed_evaluate(app)
    app.run(timeout=RUN_TIMEOUT)
    state = app.session_state["ui_navigation_state"]
    assert state.area is JourneyArea.EVALUATE
    assert state.evaluate_step is EvaluateStep.SETUP
