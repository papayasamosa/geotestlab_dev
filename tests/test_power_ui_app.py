"""AppTest coverage for the production power-analysis entry point."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from geotestlab.data import RegionalKPIConfig, prepare_regional_kpi
from tests.fixtures.live_scenarios import RUN_TIMEOUT

APP_PATH = str(Path(__file__).resolve().parent.parent / "geotestmatch.py")


def test_power_tab_explains_canonical_dataset_prerequisite():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)

    assert any("Power Analysis & Test Sizing" in item.value for item in app.subheader)
    assert any("canonical KPI dataset" in item.value for item in app.info)
    assert not app.exception


def test_media_delivery_tab_renders_without_power_dataset():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)

    assert any("Media Delivery Feasibility" in item.value for item in app.subheader)
    assert any(item.label == "Platform profile" for item in app.selectbox)
    assert any(item.label == "Default input provenance" for item in app.selectbox)
    assert not app.exception


def test_effect_plausibility_tab_renders_without_evidence():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)

    assert any("Effect Plausibility" in item.value for item in app.subheader)
    assert any(item.label == "Effectiveness evidence type" for item in app.selectbox)
    assert any(item.label == "Evidence quality" for item in app.selectbox)
    assert not app.exception


def test_design_recommendation_tab_renders_without_stage_results():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)

    assert any("Integrated Design Recommendation" in item.value for item in app.subheader)
    assert any(item.label == "Recommendation objective" for item in app.selectbox)
    assert any("Compare design candidates" in item.label for item in app.button)
    assert not app.exception


def test_power_tab_renders_explicit_design_inputs_for_canonical_dataset():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=RUN_TIMEOUT)
    dates = pd.date_range("2025-01-05", periods=6, freq="7D")
    frame = {"Region": ["A", "B"], "Metric": ["Sales", "Sales"]}
    for index, date in enumerate(dates):
        frame[date] = [float(index + 1), float(index + 2)]
    dataset = prepare_regional_kpi(pd.DataFrame(frame), RegionalKPIConfig())
    app.session_state["kpi_regional_dataset"] = dataset
    app.session_state["match_run_snapshot"] = {
        "test_geos": ["A"],
        "selected_controls": ["B"],
    }
    app.run(timeout=RUN_TIMEOUT)

    assert any(item.label == "Simulation method" for item in app.selectbox)
    assert any(item.label == "Counterfactual fit" for item in app.selectbox)
    assert any(item.label == "Frequency" for item in app.selectbox)
    assert any(item.label == "Target effect (%)" for item in app.number_input)
    assert any("Run production power" in item.label for item in app.button)
    assert any(item.label == "Scenario metric" for item in app.selectbox)
    assert any(item.label == "Market-size measure" for item in app.selectbox)
    assert any(item.label == "Target test shares (%)" for item in app.text_input)
    assert any(item.label == "Lock duration" for item in app.checkbox)
    assert any("Compare candidate scenarios" in item.label for item in app.button)
    assert any(item.label == "Force test regions" for item in app.multiselect)
    assert not app.exception
