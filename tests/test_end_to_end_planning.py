"""Deterministic integrated planning and user-facing entry-point assurance."""

from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from geotestlab.ui import PlanStep
from tests.conftest import seed_plan_step
from tests.fixtures.end_to_end_planning import (
    END_TO_END_METRIC,
    run_end_to_end_planning,
    write_end_to_end_kpi_xlsx,
)
from tests.fixtures.live_scenarios import RUN_TIMEOUT

APP_PATH = str(Path(__file__).resolve().parent.parent / "geotestmatch.py")


def test_end_to_end_planning_pipeline_freezes_exports_and_reconciles_staleness(tmp_path):
    workbook = write_end_to_end_kpi_xlsx(tmp_path / "end_to_end_aggregated.xlsx")
    artifacts = run_end_to_end_planning(workbook)

    dataset = artifacts["dataset"]
    record = artifacts["record"]
    export = artifacts["export"]
    assert dataset.config.aggregation_column == "TV Region"
    assert dataset.config.metric_column == "Metric"
    assert dataset.config.metric_value == END_TO_END_METRIC
    assert len(artifacts["sizing"].candidates) == 2
    assert all(candidate.control_regions for candidate in artifacts["sizing"].candidates)
    assert artifacts["recommendation"].selected_scenario_id == "fixture-candidate-1"
    assert len(record.frozen_versions) == 2
    assert record.frozen_versions[0].version == 1
    assert record.frozen_versions[1].version == 2
    assert export["stakeholder_summary"]["approval_status"] == "approved_design_frozen"
    assert export["technical_summary"]["active_frozen_version"]["version"] == 1
    json.dumps(export)


def test_live_app_drives_aggregated_selection_canonical_dataset_and_matching(tmp_path):
    workbook = write_end_to_end_kpi_xlsx(tmp_path / "end_to_end_live.xlsx")
    app = AppTest.from_file(APP_PATH)
    seed_plan_step(app, PlanStep.REGIONS)
    app.run(timeout=RUN_TIMEOUT)

    matching_method = [item for item in app.sidebar.radio if item.label == "Matching method"][0]
    matching_method.set_value("KPI Pattern")
    app.run(timeout=RUN_TIMEOUT)

    uploader = [
        item for item in app.sidebar.file_uploader if item.key == "kpi_pattern_sidebar_uploader"
    ][0]
    uploader.set_value(
        (
            workbook.name,
            workbook.read_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    )
    app.run(timeout=RUN_TIMEOUT)

    aggregation = [
        item for item in app.sidebar.selectbox if item.key == "kpi_pattern_agg_col_sidebar"
    ][0]
    aggregation.set_value("TV Region")
    metric = [
        item for item in app.sidebar.selectbox if item.key == "kpi_pattern_metric_value_sidebar"
    ][0]
    metric.set_value(END_TO_END_METRIC)
    app.run(timeout=RUN_TIMEOUT)

    dataset = app.session_state["kpi_pattern_regional_dataset"]
    assert dataset.config.aggregation_column == "TV Region"
    assert dataset.config.metric_value == END_TO_END_METRIC
    assert dataset.quality.inferred_frequency == "weekly"

    setup = [item for item in app.radio if item.label == "Setup Mode"][0]
    setup.set_value(setup.options[1])
    app.run(timeout=RUN_TIMEOUT)
    test_regions = [item for item in app.multiselect if item.label == "select_geographies"][0]
    test_regions.set_value([test_regions.options[0]])
    app.run(timeout=RUN_TIMEOUT)
    run_button = [item for item in app.button if "Run Match Analysis" in item.label][0]
    run_button.click()
    app.run(timeout=RUN_TIMEOUT)

    assert app.session_state["match_run_snapshot"]["test_geos"]
    assert app.session_state["final_controls"] is not None
    assert app.session_state["experiment_record"]["stage_status"]["match_quality"] == "completed"
    assert not app.exception
