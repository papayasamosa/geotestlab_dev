"""Tests for the explicit integrated design recommendation contract."""

from __future__ import annotations

import pytest

from geotestlab.recommendation import (
    DesignScenario,
    RecommendationStatus,
    assess_design_recommendation,
    recommendation_result_is_stale,
)


def _scenario(identifier: str, *, size=1.0, cost=100.0, **changes) -> DesignScenario:
    values = {
        "scenario_id": identifier,
        "size_metric": size,
        "duration_periods": 4,
        "cost": cost,
        "match_status": "supported",
        "counterfactual_status": "supported",
        "power_status": "supported",
        "power_usable": True,
        "power_meets_target": True,
        "delivery_status": "feasible",
        "effect_status": "evidence_backed",
        "effect_meets_mde": True,
        "region_constraints_status": "valid",
    }
    values.update(changes)
    return DesignScenario(**values)


def test_smallest_objective_selects_smallest_full_candidate_without_a_score():
    result = assess_design_recommendation(
        [_scenario("large", size=2.0, cost=80), _scenario("small", size=1.0, cost=120)],
        "smallest_qualifying_design",
    )

    assert result.status is RecommendationStatus.RECOMMENDED
    assert result.selected_scenario_id == "small"
    assert all("score" not in assessment.to_dict() for assessment in result.assessments)
    assert result.to_dict()["assessments"][0]["gate_statuses"]["media_delivery"] == "feasible"


def test_least_cost_objective_selects_lowest_cost_candidate():
    result = assess_design_recommendation(
        [_scenario("expensive", size=1.0, cost=200), _scenario("cheap", size=2.0, cost=75)],
        "least_cost_qualifying_design",
    )

    assert result.status is RecommendationStatus.RECOMMENDED
    assert result.selected_scenario_id == "cheap"


def test_gate_failure_is_retained_as_a_limiting_factor():
    result = assess_design_recommendation(
        [_scenario("delivery_fail", delivery_status="not_feasible")],
        "smallest_qualifying_design",
    )

    assert result.status is RecommendationStatus.NO_QUALIFYING_DESIGN
    assert result.selected_scenario_id is None
    assert "delivery_fail: media delivery status is not_feasible" in result.limiting_factors
    assessment = result.assessments[0]
    assert assessment.gate_passes["media_delivery"] is False
    assert assessment.gate_passes["power"] is True


def test_conditional_effect_is_not_reported_as_full_recommendation():
    result = assess_design_recommendation(
        [_scenario("conditional", effect_status="conditional")],
        "smallest_qualifying_design",
    )

    assert result.status is RecommendationStatus.CONDITIONAL
    assert result.selected_scenario_id == "conditional"
    assert result.assessments[0].conditional is True
    assert result.conditions


def test_least_cost_requires_cost_for_each_candidate():
    result = assess_design_recommendation(
        [_scenario("missing_cost", cost=None)],
        "least_cost_qualifying_design",
    )

    assert result.status is RecommendationStatus.NO_QUALIFYING_DESIGN
    assert "missing_cost: cost is required for the least-cost objective" in result.limiting_factors


def test_override_reason_is_required_and_exported():
    with pytest.raises(ValueError, match="override_reason is required"):
        assess_design_recommendation(
            [_scenario("a"), _scenario("b", size=2)],
            "smallest_qualifying_design",
            override_scenario_id="b",
        )

    result = assess_design_recommendation(
        [_scenario("a"), _scenario("b", size=2, delivery_status="not_feasible")],
        "smallest_qualifying_design",
        override_scenario_id="b",
        override_reason="The smaller region set is operationally unavailable.",
    )
    assert result.status is RecommendationStatus.CONDITIONAL
    assert result.selected_scenario_id == "b"
    assert result.override_applied is True
    assert result.to_dict()["override_reason"].startswith("The smaller")
    assert any("analyst override" in condition for condition in result.conditions)


def test_recommendation_fingerprint_detects_changed_candidate_inputs():
    scenarios = [_scenario("a")]
    result = assess_design_recommendation(scenarios, "smallest_qualifying_design")
    changed = [_scenario("a", cost=101)]

    assert not recommendation_result_is_stale(result, scenarios, "smallest_qualifying_design")
    assert recommendation_result_is_stale(result, changed, "smallest_qualifying_design")
