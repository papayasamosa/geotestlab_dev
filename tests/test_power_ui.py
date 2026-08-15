"""Focused coverage for the extracted power-sizing UI seams."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd
import pytest

import geotestlab.power.ui as power_ui
from geotestlab.data import MarketSizeMeasure
from geotestlab.power.scenarios import DesignAssessment, PowerScenarioCandidate


def _dataset():
    dates = pd.date_range("2025-01-05", periods=4, freq="7D")
    return SimpleNamespace(
        data=pd.DataFrame(
            {
                "region": ["A", "B", "C", "D"],
                "metric": ["Sales"] * 4,
                "date": list(dates),
            }
        ),
        metrics=("Sales",),
    )


def test_power_helpers_parse_dates_constraints_and_market_size(monkeypatch):
    dataset = _dataset()
    monkeypatch.setattr(
        power_ui.st,
        "session_state",
        {
            "match_run_snapshot": {"test_geos": ["B"], "selected_controls": ["A"]},
            "power_population_weights": {region: index + 1 for index, region in enumerate("ABCD")},
            "power_custom_weights_input": "A=2, B=3",
        },
    )

    assert power_ui._power_region_groups() == (("B",), ("A",))
    assert power_ui._power_date_strings(dataset, "Sales")[0] == "2025-01-05"
    assert (
        power_ui._power_default_date(
            power_ui._power_date_strings(dataset, "Sales"), "2025-01-12", 0
        )
        == "2025-01-12"
    )
    assert (
        power_ui._power_default_date(power_ui._power_date_strings(dataset, "Sales"), "invalid", 2)
        == "2025-01-19"
    )
    assert power_ui._parse_float_list("10, 20", "shares", percent=True) == (0.1, 0.2)
    assert power_ui._parse_int_list("2, 4", "durations") == (2, 4)
    assert power_ui._parse_custom_weights("A=2, B=3") == {"A": 2.0, "B": 3.0}
    assert MarketSizeMeasure.POPULATION in power_ui._market_size_options(dataset)
    assert power_ui._scenario_weights(MarketSizeMeasure.HISTORICAL_KPI_VOLUME, dataset) is None
    assert power_ui._scenario_weights(MarketSizeMeasure.POPULATION, dataset) == {
        "A": 1,
        "B": 2,
        "C": 3,
        "D": 4,
    }
    assert power_ui._scenario_weights(MarketSizeMeasure.CUSTOM_WEIGHT, dataset) == {
        "A": 2.0,
        "B": 3.0,
    }


def test_power_helpers_raise_actionable_input_errors(monkeypatch):
    monkeypatch.setattr(power_ui.st, "session_state", {})

    with pytest.raises(ValueError, match="comma-separated numbers"):
        power_ui._parse_float_list("10, nope", "shares")
    with pytest.raises(ValueError, match="finite"):
        power_ui._parse_float_list("nan", "shares")
    with pytest.raises(ValueError, match="positive whole"):
        power_ui._parse_int_list("0, -1", "durations")
    with pytest.raises(ValueError, match="comma-separated whole"):
        power_ui._parse_int_list("two", "durations")
    with pytest.raises(ValueError, match="Region=weight"):
        power_ui._parse_custom_weights("A:2")
    with pytest.raises(ValueError, match="not numeric"):
        power_ui._parse_custom_weights("A=nope")
    with pytest.raises(ValueError, match="positive values"):
        power_ui._parse_custom_weights("A=0")
    with pytest.raises(ValueError, match="at least one"):
        power_ui._parse_custom_weights("")
    with pytest.raises(ValueError, match="Population weights"):
        power_ui._scenario_weights(MarketSizeMeasure.POPULATION, _dataset())
    assert MarketSizeMeasure.POPULATION not in power_ui._market_size_options(_dataset())


def test_power_region_group_fallback_and_scenario_results(monkeypatch):
    controls = pd.DataFrame({"region": ["C", "D"]})
    monkeypatch.setattr(
        power_ui.st,
        "session_state",
        {
            "match_run_snapshot": {},
            "selected_experiment_regions": ["A"],
            "final_controls": controls,
            "geo_col": "region",
        },
    )
    assert power_ui._power_region_groups() == (("A",), ("C", "D"))

    assessment = DesignAssessment(
        match_status="pass",
        counterfactual_status="supported",
        match_metrics={"balance": 0.1},
        counterfactual_metrics={"placebo": 0.9},
        warnings=("review",),
        blockers=("power blocker",),
        matching_method="intermediate",
        matching_seed=42,
        validation_method="enet",
        control_selection_provenance={"source": "test"},
    )
    power = SimpleNamespace(
        mde=4.0,
        power_at_target_effects=(0.82,),
        support_status="supported",
        effect_grid=(0.0, 5.0),
        power_curve=(0.2, 0.82),
        power_ci_lower=(0.1, 0.7),
        power_ci_upper=(0.3, 0.9),
        input_fingerprint="fp1:input",
        source_data_fingerprint="fp1:source",
        blockers=("power blocker",),
        warnings=("power warning",),
    )
    candidates = (
        PowerScenarioCandidate(
            requested_share=0.2,
            actual_share=0.21,
            share_difference=0.01,
            market_size_measure=MarketSizeMeasure.HISTORICAL_KPI_VOLUME.value,
            duration_periods=4,
            planned_test_dates=("2025-02-01",),
            test_regions=("A",),
            control_regions=("B",),
            design_assessment=assessment,
            power_result=power,
            recommendation_eligible=True,
            recommendation_blockers=(),
        ),
        PowerScenarioCandidate(
            requested_share=0.4,
            actual_share=0.39,
            share_difference=-0.01,
            market_size_measure=MarketSizeMeasure.CUSTOM_WEIGHT.value,
            duration_periods=8,
            planned_test_dates=(),
            test_regions=("C",),
            control_regions=("D",),
            design_assessment=assessment,
            recommendation_eligible=False,
            recommendation_blockers=("power unsupported",),
        ),
    )
    result = SimpleNamespace(candidates=candidates)
    monkeypatch.setattr(power_ui.st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(power_ui.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "warning", lambda *args, **kwargs: None)

    power_ui._render_scenario_results(result)


def test_selected_design_power_run_and_short_dataset_warning(monkeypatch):
    dataset = _dataset()
    result = SimpleNamespace(
        completed=True,
        support_status="supported",
        mde=4.0,
        power_at_target_effects=(0.82,),
        effective_test_periods=1,
        blockers=("result blocker",),
        warnings=("result warning",),
        effect_grid=(0.0, 5.0),
        power_curve=(0.2, 0.82),
        power_ci_lower=(0.1, 0.7),
        power_ci_upper=(0.3, 0.9),
        to_dict=lambda: {"status": "supported"},
    )

    class Column:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def metric(self, *args, **kwargs):
            return None

    class SessionState(dict):
        def __getattr__(self, name):
            return self.get(name)

        def __setattr__(self, name, value):
            self[name] = value

    def selectbox(label, options, **kwargs):
        if label == "Frequency":
            return "weekly"
        if label == "Simulation method":
            return "model_simulation"
        if label == "Counterfactual fit":
            return "ols"
        if label == "Effect direction":
            return "one_sided_positive"
        return options[0]

    def multiselect(_label, options, **kwargs):
        return kwargs.get("default", list(options[:1]))

    monkeypatch.setattr(power_ui.st, "session_state", SessionState())
    monkeypatch.setattr(power_ui.st, "form", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(power_ui.st, "selectbox", selectbox)
    monkeypatch.setattr(power_ui.st, "multiselect", multiselect)
    monkeypatch.setattr(power_ui.st, "checkbox", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        power_ui.st,
        "number_input",
        lambda _label, **kwargs: kwargs.get("value", kwargs.get("min_value", 1)),
    )
    monkeypatch.setattr(power_ui.st, "date_input", lambda _label, **kwargs: kwargs["value"])
    monkeypatch.setattr(power_ui.st, "columns", lambda count: [Column() for _ in range(count)])
    monkeypatch.setattr(power_ui.st, "form_submit_button", lambda *args, **kwargs: True)
    monkeypatch.setattr(power_ui.st, "spinner", lambda *_args, **_kwargs: nullcontext())
    for name in ("success", "warning", "error", "info", "caption", "markdown"):
        monkeypatch.setattr(power_ui.st, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "line_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui.st, "download_button", lambda *args, **kwargs: None)
    monkeypatch.setattr(power_ui, "run_production_power", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(power_ui, "production_result_is_stale", lambda *_args, **_kwargs: False)

    power_ui._render_selected_design_power(
        dataset, ("A",), ("B",), experiment_record_factory=None, save_experiment_record=None
    )
    assert power_ui.st.session_state["production_power_result"] is result

    def stale_error(*_args, **_kwargs):
        raise TypeError("stale result")

    monkeypatch.setattr(power_ui, "production_result_is_stale", stale_error)
    power_ui._render_selected_design_power(
        dataset, ("A",), ("B",), experiment_record_factory=None, save_experiment_record=None
    )

    short_dataset = SimpleNamespace(
        data=dataset.data.iloc[[0]].copy(),
        metrics=("Sales",),
    )
    power_ui._render_selected_design_power(
        short_dataset, ("A",), ("B",), experiment_record_factory=None, save_experiment_record=None
    )
