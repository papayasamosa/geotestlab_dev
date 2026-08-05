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

import os
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from geotestlab.experiment import material_file_identity
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

# Minimal geography workbook regions (must include the match fixture regions).
GEO_REGIONS = [
    "Aberdeen City",
    "Aberdeenshire",
    "Angus",
    "Argyll and Bute",
    "Clackmannanshire",
    "Dundee City",
    "East Ayrshire",
]


def _write_geo_workbook(path: Path, regions, market="UK", population_delta=0) -> Path:
    """Write a minimal geography workbook with one market sheet (same columns as
    the bundled standardised file: Adobe Reference List, Local Authority Area,
    Population, Population Density)."""
    df = pd.DataFrame(
        {
            "Adobe Reference List": [f"ADB-{i:02d}" for i in range(len(regions))],
            "Local Authority Area": regions,
            "Population": [100_000 - i * 5_000 + population_delta for i in range(len(regions))],
            "Population Density": [400.0 + i * 12.5 for i in range(len(regions))],
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=market, index=False)
    return path


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


def test_design_validation_does_not_complete_observed_impact(tmp_path: Path):
    """Design-mode validation (no completed-test evaluation) must NOT complete
    observed_impact — merely having selected test periods is insufficient."""
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly_design.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "design", "weekly_design.xlsx", kpi_path.read_bytes())
    run_btn = [b for b in app.button if b.key == "design_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    rec = _record(app)
    # counterfactual_validation is completed; observed_impact is NOT.
    assert rec["stage_status"]["counterfactual_validation"] == "completed"
    assert rec["stage_status"]["observed_impact"] in ("not_started", "planned")
    assert "observed_impact" not in rec["stage_fingerprints"]


def test_freeze_stores_executed_matching_and_quality_fields(tmp_path: Path):
    """The frozen design's matching section is reconstructed from the executed
    match snapshot (method, mode, setup, regions, controls, exclusions, weights,
    share, market, geography level, KPI pattern) and the data-quality summary
    stores separate fields (never a collapsed uncovered_regions)."""
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly_freeze.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "design", "weekly_freeze.xlsx", kpi_path.read_bytes())
    run_btn = [b for b in app.button if b.key == "design_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)
    freeze_btn = [b for b in app.button if b.key == "freeze_design_btn"][0]
    freeze_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    frozen = _record(app)["frozen_versions"][0]
    matching = frozen["design"]["matching"]
    # executed-match values (from match_run_snapshot, not live widget state)
    assert matching["matching_method"] == "Structural"
    assert matching["match_mode"] == "User Selected"
    assert matching["setup_mode"] == "Manual Selection (Pick Both)"
    assert matching["executed_strategy"] == "User Selected"
    assert matching["market"] == "UK"
    assert matching["geography_level"] == "Local Authority Area"
    assert TEST_REGION in matching["test_regions"]
    assert set(matching["selected_controls"]) == set(CONTROL_REGIONS)
    assert matching["feature_weights"]
    # region exclusions are separate from time-period exclusions
    assert set(matching["region_exclusions"]) == {
        "global",
        "test_only",
        "control_only",
        "forced_test_regions",
        "forced_control_eligibility",
    }
    assert set(matching["time_period_exclusions"]) == {"manual", "tracking_outages"}
    assert matching["test_share"]["target"] == 25
    assert matching["test_share"]["achieved"] is not None

    # data-quality summary stores separate fields
    dq = frozen["design"]["data_quality_summary"]
    assert "uncovered_regions" not in dq
    assert "raw_regions" in dq
    assert "unmapped_raw_regions" in dq
    assert "covered_regions" in dq
    assert "required_regions_without_coverage" in dq
    assert "blocking_errors" in dq
    assert "warnings" in dq
    assert TEST_REGION in dq["covered_regions"]

    # tool version is derived from package metadata (never hardcoded 0.3.0)
    from geotestlab.experiment import tool_version

    assert frozen["design"]["tool_version"] == tool_version()


def test_same_content_workbook_replacement_invalidates_caches(tmp_path, monkeypatch):
    """The workbook/market-sheet caches are keyed on material file identity
    (path + size + mtime_ns), so replacing the bundled workbook invalidates the
    market sheet even when the path is unchanged. (Exact same-size detection is
    covered by the pure material_file_identity test.)"""
    wb_path = _write_geo_workbook(tmp_path / "geo.xlsx", GEO_REGIONS)
    monkeypatch.setenv("GEOTESTLAB_DATA_PATH", str(wb_path))
    kpi_path = write_correlated_kpi_xlsx(
        tmp_path / "weekly_cache.xlsx",
        TEST_REGION,
        CONTROL_REGIONS,
        metric_name="Sales",
        n_periods=60,
        freq="W",
        seed=123,
    )
    app = _new_app()
    _manual_match(app)
    _upload_kpi(app, "design", "weekly_cache.xlsx", kpi_path.read_bytes())
    run_btn = [b for b in app.button if b.key == "design_run_button"][0]
    run_btn.click()
    app.run(timeout=RUN_TIMEOUT)

    wb_cache = app.session_state["experiment_geo_workbook_cache"]
    sheet_cache = app.session_state["experiment_market_sheet_cache"]
    identity_a = wb_cache[0]
    assert set(identity_a) == {"path", "size", "mtime_ns"}  # not just size
    assert sheet_cache[0][0] == "sheet"
    assert sheet_cache[0][1] == "UK"
    assert sheet_cache[0][2] == identity_a  # market sheet keyed on workbook identity

    # Replace the workbook at the same path with different content.
    _write_geo_workbook(wb_path, GEO_REGIONS, market="UK", population_delta=999)
    stat = os.stat(wb_path)
    os.utime(wb_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    identity_b = material_file_identity(str(wb_path))
    assert identity_b != identity_a

    # Re-running the app invalidates the market sheet and re-reads it.
    app.run(timeout=RUN_TIMEOUT)
    sheet_cache2 = app.session_state["experiment_market_sheet_cache"]
    assert sheet_cache2[0][2] == identity_b
    assert sheet_cache2[0][2] != identity_a
    sheet2 = sheet_cache2[1]
    assert sheet2 is not None
    assert float(sheet2["Population"].iloc[0]) == pytest.approx(100_999)
