"""Tests for the typed upstream recommendation adapter and UI boundary."""

from __future__ import annotations

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

import geotestlab.recommendation.ui as recommendation_ui
from geotestlab.data import MarketSizeMeasure
from geotestlab.effect.plausibility import EffectComparison, EffectPlausibilityStatus
from geotestlab.matching.models import MatchConstraints
from geotestlab.media.delivery import DeliveryStatus
from geotestlab.media.profiles import InputProvenance, MediaValue
from geotestlab.power.scenarios import (
    DesignAssessment,
    PowerScenarioCandidate,
    ScenarioSizingConfig,
)
from tests.fixtures.live_scenarios import RUN_TIMEOUT


def _candidate(*, source_fingerprint: str = "source") -> PowerScenarioCandidate:
    power = SimpleNamespace(
        source_data_fingerprint=source_fingerprint,
        target_power=0.8,
        mde=4.0,
        power_at_target_effects=(0.86,),
        support_status="supported",
        usable_for_recommendation=True,
        historical_data_sufficiency={"retained_periods": 40},
        input_fingerprint="power-input",
        to_dict=lambda: {
            "source_data_fingerprint": source_fingerprint,
            "input_fingerprint": "power-input",
        },
    )
    return PowerScenarioCandidate(
        requested_share=0.20,
        actual_share=0.17,
        share_difference=-0.03,
        market_size_measure=MarketSizeMeasure.POPULATION.value,
        duration_periods=6,
        planned_test_dates=("2025-02-01",),
        test_regions=("A",),
        control_regions=("B",),
        design_assessment=DesignAssessment(
            match_status="pass",
            counterfactual_status="supported",
            match_metrics={"smd": 0.1},
            counterfactual_metrics={"placebo": 0.9},
            matching_method="intermediate",
            matching_seed=42,
            validation_method="enet",
            control_selection_provenance={"source": "typed-test-double"},
        ),
        power_result=power,
        recommendation_eligible=True,
        recommendation_blockers=(),
    )


def _state(candidate, *, source_fingerprint: str = "source") -> dict:
    delivery = SimpleNamespace(
        status=DeliveryStatus.FEASIBLE,
        input_fingerprint="delivery-input",
        values={
            "total_budget": MediaValue(
                1250.0,
                InputProvenance.ANALYST_ASSUMPTION,
                source="test",
            )
        },
        to_dict=lambda: {"status": "feasible", "input_fingerprint": "delivery-input"},
    )
    effect = SimpleNamespace(
        status=EffectPlausibilityStatus.EVIDENCE_BACKED,
        input_fingerprint="effect-input",
        comparisons=(EffectComparison("central", 5.0, 4.0, True, 1.0),),
        to_dict=lambda: {"status": "evidence_backed", "input_fingerprint": "effect-input"},
    )
    return {
        "power_scenario_result": SimpleNamespace(
            candidates=(candidate,),
            metric="Sales",
            market_size_measure=MarketSizeMeasure.POPULATION.value,
            total_market_size=10000.0,
        ),
        "power_scenario_config": ScenarioSizingConfig(
            constraints=MatchConstraints(
                force_test_include=("A",),
                force_control_include=("B",),
            )
        ),
        "kpi_regional_dataset": SimpleNamespace(source_data_fingerprint=source_fingerprint),
        "media_delivery_result": delivery,
        "effect_plausibility_result": effect,
    }


def test_upstream_adapter_uses_actual_share_and_preserves_provenance(monkeypatch):
    candidate = _candidate()
    monkeypatch.setattr(recommendation_ui.st, "session_state", _state(candidate))
    monkeypatch.setattr(recommendation_ui, "_delivery_is_current", lambda result: True)
    monkeypatch.setattr(recommendation_ui, "_effect_is_current", lambda result, current: True)

    scenarios = recommendation_ui._upstream_scenarios()

    assert len(scenarios) == 1
    scenario = scenarios[0]
    assert scenario.size_metric == 0.17
    assert scenario.size_metric != candidate.requested_share
    assert scenario.duration_periods == 6
    assert scenario.cost == 1250.0
    assert scenario.match_status == "pass"
    assert scenario.counterfactual_status == "supported"
    assert scenario.power_status == "supported"
    assert scenario.power_usable is True
    assert scenario.power_meets_target is True
    assert scenario.delivery_status == "feasible"
    assert scenario.effect_status == "evidence_backed"
    assert scenario.effect_meets_mde is True
    assert scenario.region_constraints_status == "pass"
    assert scenario.history_periods == 40
    assert scenario.metadata["source"] == "power_scenario_result"
    assert scenario.metadata["analyst_supplied"] is False
    assert scenario.metadata["market_size_measure"] == MarketSizeMeasure.POPULATION.value
    assert scenario.metadata["test_regions"] == ["A"]
    assert scenario.metadata["control_regions"] == ["B"]


def test_effect_gate_uses_each_candidate_mde(monkeypatch):
    candidate = _candidate()
    candidate.power_result.mde = 6.0
    monkeypatch.setattr(recommendation_ui.st, "session_state", _state(candidate))
    monkeypatch.setattr(recommendation_ui, "_delivery_is_current", lambda result: True)
    monkeypatch.setattr(recommendation_ui, "_effect_is_current", lambda result, current: True)

    scenario = recommendation_ui._upstream_scenarios()[0]

    assert scenario.effect_status == "evidence_backed"
    assert scenario.effect_meets_mde is False


def test_stale_candidate_power_cannot_become_qualifying_in_adapter(monkeypatch):
    candidate = _candidate(source_fingerprint="old-source")
    monkeypatch.setattr(
        recommendation_ui.st,
        "session_state",
        _state(candidate, source_fingerprint="new-source"),
    )
    monkeypatch.setattr(recommendation_ui, "_delivery_is_current", lambda result: True)
    monkeypatch.setattr(recommendation_ui, "_effect_is_current", lambda result, current: True)

    scenario = recommendation_ui._upstream_scenarios()[0]

    assert scenario.power_status == "stale"
    assert scenario.power_usable is False
    assert scenario.power_meets_target is None


def test_manual_scenarios_are_explicitly_analyst_supplied():
    scenario = recommendation_ui._scenario_from_row(
        {
            "scenario_id": "manual",
            "size_metric": 0.2,
            "duration_periods": 4,
            "match_status": "pass",
            "counterfactual_status": "supported",
            "power_status": "supported",
            "power_usable": True,
            "power_meets_target": True,
            "delivery_status": "feasible",
            "effect_status": "evidence_backed",
            "effect_meets_mde": True,
            "region_constraints_status": "pass",
        }
    )

    assert scenario.metadata == {"source": "analyst_supplied", "analyst_supplied": True}


def test_recommendation_uses_read_only_upstream_candidates():
    app = AppTest.from_string(
        "from geotestlab.recommendation.ui import render_design_recommendation_tab\n"
        "render_design_recommendation_tab()\n"
    )
    candidate = _candidate()
    state = _state(candidate)
    app.run(timeout=RUN_TIMEOUT)
    for key, value in state.items():
        app.session_state[key] = value
    app.run(timeout=RUN_TIMEOUT)

    assert len(app.get("data_editor")) == 0
    assert any("read-only" in item.value for item in app.info)
    assert not app.exception
