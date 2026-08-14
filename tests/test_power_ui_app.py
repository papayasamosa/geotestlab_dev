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
    assert not app.exception
