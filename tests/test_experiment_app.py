"""Stage 4: experiment identity, fingerprints, stage status, freeze, staleness.

AppTest coverage of the live workflow record:
- the experiment panel renders on a fresh app with default stage statuses;
- a completed manual match stamps match_quality and stores matching inputs;
- a completed design validation stamps counterfactual_validation, stores the
  analysed summary, and enables the design-freeze button;
- freezing records an immutable approved version;
- changing a validation input (historical period) clears the validation result
  and reconciles the record so counterfactual_validation becomes stale.

The pure experiment-core logic is covered separately in
``tests/test_experiment_core.py``.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.fixture_factories.write_correlated_kpi_xlsx import write_correlated_kpi_xlsx
from tests.fixtures.live_scenarios import (
    CONTROL_REGIONS,
    RUN_TIMEOUT,
    TEST_REGION,
    _manual_match,
    _upload_kpi,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(REPO_ROOT / "geotestmatch.py")


def _new_app() -> AppTest:
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)
    return app


def _record(app: AppTest) -> dict:
    return dict(app.session_state["experiment_record"])


def test_experiment_panel_renders_with_default_stage_statuses():
    app = _new_app()
    assert any("Experiment record" in e.label for e in app.expander), (
        "experiment panel should render on a fresh app"
    )
    rec = _record(app)
    assert rec["experiment_id"].startswith("EXP-")
    assert rec["stage_status"]["match_quality"] == "not_started"
    assert rec["stage_status"]["statistical_power"] == "planned"
    assert rec["stage_status"]["media_delivery"] == "planned"
    assert rec["stage_status"]["effect_plausibility"] == "planned"
    assert rec["stage_status"]["counterfactual_validation"] == "not_started"


def test_matching_completion_stamps_match_quality():
    app = _new_app()
    _manual_match(app)
    rec = _record(app)
    assert rec["stage_status"]["match_quality"] == "completed"
    assert rec["stage_fingerprints"]["match_quality"].startswith("fp1:")
    assert app.session_state["experiment_matching_inputs"] is not None


def test_validation_completion_stamps_and_freeze(tmp_path: Path):
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "design", "weekly.xlsx", kpi_path.read_bytes())

    run_btn = [b for b in app.button if b.key == "design_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    rec = _record(app)
    assert rec["stage_status"]["match_quality"] == "completed"
    assert rec["stage_status"]["counterfactual_validation"] == "completed"
    assert rec["stage_fingerprints"]["counterfactual_validation"].startswith("fp1:")
    assert rec["analysed"] is not None
    assert rec["analysed"]["planned_test_periods"] is not None
    assert app.session_state["experiment_validation_inputs"] is not None

    # Freeze the approved design.
    freeze_btn = [b for b in app.button if b.key == "freeze_design_btn"][0]
    assert freeze_btn.disabled is False
    freeze_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    rec = _record(app)
    assert len(rec["frozen_versions"]) == 1
    frozen = rec["frozen_versions"][0]
    assert frozen["version"] == 1
    assert frozen["schema_version"] == "frozen-design/v1"
    assert frozen["planned"]["planned_test_periods"] == rec["analysed"]["planned_test_periods"]
    # A complete design snapshot is captured, not just a fingerprint + periods.
    assert frozen["design"]["test_regions"]
    assert frozen["design"]["control_regions"]
    assert frozen["design"]["tool_version"]
    assert frozen["design"]["methodology_version"]
    assert (
        frozen["design"]["planned_test_period"]["planned_test_periods"]
        == rec["analysed"]["planned_test_periods"]
    )
    assert frozen["design"]["source_data_digests"]["source_bytes"].startswith("sha256:")


def test_changing_validation_input_marks_stage_stale(tmp_path: Path):
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "design", "weekly.xlsx", kpi_path.read_bytes())

    run_btn = [b for b in app.button if b.key == "design_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)
    assert _record(app)["stage_status"]["counterfactual_validation"] == "completed"

    # Change the historical-period start -> clear_validation_state runs. Use a
    # middle option so start < end (the last option would equal the default end
    # and hit the app's "Start date must be before end date" stop).
    start_sb = [s for s in app.selectbox if s.key == "design_design_start"][0]
    start_sb.set_value(start_sb.options[len(start_sb.options) // 2])
    app.run(timeout=RUN_TIMEOUT)

    rec = _record(app)
    # The validation result and its inputs are cleared; the record reconciles
    # the stage to stale rather than silently keeping the old result.
    assert app.session_state["validation_results"] is None
    assert app.session_state["experiment_validation_inputs"] is None
    assert rec["stage_status"]["counterfactual_validation"] == "stale"
    assert rec["stage_stale"]["counterfactual_validation"] is True


def test_validation_completes_observed_impact_without_bayesian(tmp_path: Path):
    """A completed-test evaluation (Evaluate mode) stamps observed_impact
    completed WITHOUT a Bayesian run; content SHA-256 digests are part of the
    validation identity."""
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly_eval.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "evaluate", "weekly_eval.xlsx", kpi_path.read_bytes())

    run_btn = [b for b in app.button if b.key == "evaluate_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    rec = _record(app)
    assert rec["stage_status"]["observed_impact"] == "completed"
    assert rec["stage_fingerprints"]["observed_impact"].startswith("fp1:")
    assert rec["stage_stale"]["observed_impact"] is False
    # Content digests are stored (digests only) and part of the validation inputs.
    vinputs = app.session_state["experiment_validation_inputs"]
    assert vinputs["content_digests"]["source_bytes"].startswith("sha256:")
    assert vinputs["content_digests"]["analytical_data"].startswith("sha256:")
    assert vinputs["content_digests"]["geography_workbook"].startswith("sha256:")
    assert rec["content_digests"]["source_bytes"].startswith("sha256:")
    # No Bayesian inputs/result were required.
    assert app.session_state["experiment_bayesian_inputs"] is None
