"""Tests for explicit market-share and duration scenario sizing."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from geotestlab.data import MarketSizeMeasure, RegionalKPIConfig, prepare_regional_kpi
from geotestlab.matching import MatchConstraints
from geotestlab.power.production import ProductionPowerConfig, ProductionPowerResult
from geotestlab.power.scenarios import (
    ControlSelection,
    DesignAssessment,
    PowerScenarioCandidate,
    ScenarioSizingConfig,
    select_smallest_qualifying,
    size_power_scenarios,
)


def _dataset():
    dates = pd.date_range("2025-01-05", periods=4, freq="7D")
    regions = ["A", "B", "C", "D", "E", "F", "G", "Large"]
    weights = [1, 1, 1, 1, 1, 1, 1, 10]
    frame = {"Region": regions, "Metric": ["Sales"] * len(regions)}
    # Make the large region genuinely large at every date rather than relying
    # on a region-count approximation.
    for date in dates:
        frame[date] = [float(weight) for weight in weights]
    return prepare_regional_kpi(pd.DataFrame(frame), RegionalKPIConfig())


def _assessment(*_args) -> DesignAssessment:
    return DesignAssessment(match_status="pass", counterfactual_status="pass")


def _template() -> ProductionPowerConfig:
    dates = pd.date_range("2025-01-05", periods=4, freq="7D")
    return ProductionPowerConfig(
        method="model_simulation",
        fit_method="ols",
        test_regions=("A",),
        control_regions=("B",),
        historical_start=dates[0],
        historical_end=dates[2],
        historical_holdout_dates=(dates[3],),
        planned_duration_periods=1,
        target_effects=(5.0,),
        mde_bounds=(0.0, 10.0),
        n_simulations=100,
    )


def _power_result(**changes) -> ProductionPowerResult:
    values = {
        "production_contract_version": "1.1.0",
        "methodology_version": "0.5.0",
        "evidence_commit": "evidence",
        "input_fingerprint": "fp1:scenario",
        "source_data_fingerprint": "source",
        "metric": "Sales",
        "method": "model_simulation",
        "fit_method": "ols",
        "fit_status": "ok",
        "detection_criterion": "interval_excludes_zero",
        "effect_injection": "relative",
        "effect_shape": "step",
        "side": "one_sided_positive",
        "frequency": "weekly",
        "alpha": 0.05,
        "target_power": 0.8,
        "n_simulations": 100,
        "random_seed": 1,
        "test_regions": ("A",),
        "control_regions": ("B",),
        "historical_start": "2025-01-05",
        "historical_end": "2025-01-19",
        "planned_test_dates": ("2025-01-26",),
        "target_effects": (5.0,),
        "power_at_target_effects": (0.9,),
        "power_ci_at_target_effects": ((0.8, 0.95),),
        "effect_grid": (0.0, 5.0, 10.0),
        "power_curve": (0.05, 0.9, 0.99),
        "power_ci_lower": (0.01, 0.8, 0.95),
        "power_ci_upper": (0.1, 0.95, 1.0),
        "mde": 4.0,
        "mde_reached": True,
        "mde_bounds": (0.0, 10.0),
        "uncertainty_kind": "conditional_clopper_pearson",
        "uncertainty_is_unconditional": False,
        "effective_test_periods": 1,
        "requested_test_periods": 1,
        "windows_available": 5,
        "windows_used": 5,
        "support_status": "supported",
        "completed": True,
        "usable_for_recommendation": True,
    }
    values.update(changes)
    return ProductionPowerResult(**values)


def test_historical_kpi_share_is_not_region_count_share():
    dataset = _dataset()
    requested = 5 / 17

    result = size_power_scenarios(
        dataset,
        ScenarioSizingConfig(
            target_shares=(requested,),
            durations=(1,),
            historical_end=pd.Timestamp("2025-01-19"),
            share_tolerance=0.001,
        ),
        design_assessor=_assessment,
    )

    candidate = result.candidates[0]
    assert candidate.market_size_measure == MarketSizeMeasure.HISTORICAL_KPI_VOLUME.value
    assert candidate.actual_share == pytest.approx(requested)
    assert candidate.actual_share != pytest.approx(5 / 8)
    assert len(candidate.test_regions) == 5
    assert result.total_market_size == pytest.approx(17 * 3)


def test_population_measure_requires_explicit_weights():
    with pytest.raises(ValueError, match="requires explicit regional_weights"):
        size_power_scenarios(
            _dataset(),
            ScenarioSizingConfig(
                target_shares=(0.2,),
                durations=(1,),
                historical_end=pd.Timestamp("2025-01-19"),
                market_size_measure=MarketSizeMeasure.POPULATION,
            ),
        )


def test_explicit_weights_must_cover_dataset_regions():
    dataset = _dataset()
    weights = {str(region): 1.0 for region in dataset.data["region"].unique()}
    weights["Unexpected"] = 1.0

    with pytest.raises(ValueError, match="unknown regions"):
        size_power_scenarios(
            dataset,
            ScenarioSizingConfig(
                target_shares=(0.2,),
                durations=(1,),
                historical_end=pd.Timestamp("2025-01-19"),
                market_size_measure=MarketSizeMeasure.POPULATION,
                regional_weights=weights,
            ),
        )


def test_constraints_and_locked_groups_are_retained():
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=pd.Timestamp("2025-01-19"),
            constraints=MatchConstraints(
                force_test_include=("A",),
                force_control_include=("B",),
                exclude_from_both=("G",),
            ),
            locked_test_regions=("A", "C"),
            locked_control_regions=("B", "D"),
        ),
        design_assessor=_assessment,
    )

    candidate = result.candidates[0]
    assert candidate.test_regions == ("A", "C")
    assert candidate.control_regions == ("B", "D")
    assert "G" not in candidate.test_regions + candidate.control_regions


def test_indivisible_share_outside_tolerance_is_a_candidate_blocker():
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=pd.Timestamp("2025-01-19"),
            locked_test_regions=("Large",),
            share_tolerance=0.01,
        ),
    )

    candidate = result.candidates[0]
    assert candidate.actual_share == pytest.approx(10 / 17)
    assert any(
        "outside the requested share tolerance" in value
        for value in candidate.design_assessment.blockers
    )
    assert candidate.recommendation_eligible is False


def test_locked_test_regions_must_retain_forced_test_regions():
    with pytest.raises(ValueError, match="omit a forced test region"):
        size_power_scenarios(
            _dataset(),
            ScenarioSizingConfig(
                target_shares=(0.2,),
                durations=(1,),
                historical_end=pd.Timestamp("2025-01-19"),
                constraints=MatchConstraints(force_test_include=("B",)),
                locked_test_regions=("A",),
            ),
        )


def test_default_power_runner_receives_dataset(monkeypatch):
    dataset = _dataset()
    template = replace(_template(), planned_test_dates=(pd.Timestamp("2025-02-02"),))
    received = {}

    def fake_runner(received_dataset, config):
        received["dataset"] = received_dataset
        received["config"] = config
        return _power_result(
            test_regions=config.test_regions,
            control_regions=config.control_regions,
            planned_test_dates=tuple(value.isoformat() for value in config.planned_test_dates),
        )

    monkeypatch.setattr("geotestlab.power.scenarios.run_production_power", fake_runner)
    result = size_power_scenarios(
        dataset,
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=template.historical_end,
            power_template=template,
        ),
        design_assessor=_assessment,
    )

    assert received["dataset"] is dataset
    assert result.candidates[0].power_result is not None
    assert result.candidates[0].planned_test_dates == ("2025-02-02T00:00:00",)
    assert len(received["config"].control_regions) == len(received["config"].test_regions)
    assert received["config"].historical_holdout_dates == (pd.Timestamp("2025-01-26"),)


def test_default_builder_matches_controls_instead_of_using_all_remaining_regions():
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=pd.Timestamp("2025-01-19"),
        ),
    )

    candidate = result.candidates[0]
    assert len(candidate.control_regions) == len(candidate.test_regions)
    assert len(candidate.control_regions) < 8 - len(candidate.test_regions)
    assert candidate.design_assessment.match_metrics["control_group_size"] == len(
        candidate.control_regions
    )
    assert candidate.design_assessment.matching_method == "intermediate"
    assert candidate.power_result is None
    assert candidate.recommendation_eligible is False


def test_power_uses_actual_matched_design_even_when_validation_blocks():
    received = {}

    def runner(config):
        received["config"] = config
        return _power_result(
            test_regions=config.test_regions,
            control_regions=config.control_regions,
        )

    template = _template()
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=template.historical_end,
            power_template=template,
        ),
        power_runner=runner,
    )

    candidate = result.candidates[0]
    assert received["config"].control_regions == candidate.control_regions
    assert len(received["config"].control_regions) == len(candidate.test_regions)
    assert candidate.design_assessment.counterfactual_status == "fail"
    assert candidate.recommendation_eligible is False


def test_typed_control_and_validation_seams_receive_the_real_candidate_design():
    received = {}

    def selector(_dataset, request):
        received["request"] = request
        return ControlSelection(
            control_regions=("B",),
            match_status="pass",
            match_metrics={"mean_abs_smd": 0.01},
            provenance={"source": "test-selector"},
        )

    def validator(_dataset, request, design):
        received["design"] = design
        assert request.test_regions == ("A",)
        assert request.validation_method == "enet"
        assert design.control_regions == ("B",)
        return DesignAssessment(match_status="pass", counterfactual_status="pass")

    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=pd.Timestamp("2025-01-19"),
            locked_test_regions=("A",),
            control_selector=selector,
            validation_runner=validator,
        ),
    )

    candidate = result.candidates[0]
    assert received["request"].actual_share == pytest.approx(1 / 17)
    assert received["design"].control_regions == ("B",)
    assert candidate.control_regions == ("B",)
    assert candidate.design_assessment.control_selection_provenance == {"source": "test-selector"}


def test_unavailable_duration_is_retained_as_blocked_candidate():
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1, 2),
            historical_end=pd.Timestamp("2025-01-19"),
        ),
        design_assessor=_assessment,
    )

    assert len(result.candidates) == 2
    unavailable = result.candidates[1]
    assert unavailable.planned_test_dates == ()
    assert "duration 2 cannot be built" in unavailable.design_assessment.blockers[0]
    assert unavailable.recommendation_eligible is False


def test_design_assessment_blockers_prevent_recommendation():
    template = _template()
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=template.historical_end,
            power_template=template,
            objective="smallest_test_share_then_duration",
        ),
        design_assessor=lambda *_args: DesignAssessment(
            match_status="pass",
            counterfactual_status="pass",
            blockers=("contamination risk",),
        ),
        power_runner=lambda _config: _power_result(),
    )

    assert result.selected_candidate is None
    assert result.candidates[0].recommendation_eligible is False
    assert "contamination risk" in result.candidates[0].recommendation_blockers


def test_power_template_and_sizing_history_must_match():
    template = _template()
    with pytest.raises(ValueError, match="historical_end must match"):
        size_power_scenarios(
            _dataset(),
            ScenarioSizingConfig(
                target_shares=(0.2,),
                durations=(1,),
                historical_end=pd.Timestamp("2025-01-12"),
                power_template=template,
            ),
        )


def test_poor_design_quality_blocks_recommendation_even_with_power():
    template = _template()
    result = size_power_scenarios(
        _dataset(),
        ScenarioSizingConfig(
            target_shares=(0.2,),
            durations=(1,),
            historical_end=template.historical_end,
            power_template=template,
            objective="smallest_test_share_then_duration",
        ),
        design_assessor=lambda *_args: DesignAssessment(
            match_status="fail", counterfactual_status="fail"
        ),
        power_runner=lambda _config: _power_result(),
    )

    assert result.selected_candidate is None
    assert result.candidates[0].recommendation_eligible is False
    assert (
        "match/counterfactual quality does not pass" in result.candidates[0].recommendation_blockers
    )


def test_explicit_objective_selects_smallest_qualifying_candidate():
    first = PowerScenarioCandidate(
        requested_share=0.2,
        actual_share=0.25,
        share_difference=0.05,
        market_size_measure="historical_kpi_volume",
        duration_periods=4,
        planned_test_dates=(),
        test_regions=(),
        control_regions=(),
        design_assessment=_assessment(),
        recommendation_eligible=True,
    )
    second = replace(first, actual_share=0.3, duration_periods=2)

    assert select_smallest_qualifying((second, first), "smallest_test_share_then_duration") == 1
    with pytest.raises(ValueError, match="unknown optimisation objective"):
        select_smallest_qualifying((first,), "best_magic_score")
