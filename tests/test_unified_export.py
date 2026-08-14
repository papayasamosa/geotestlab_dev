"""Tests for the unified typed-result export section."""

from __future__ import annotations

import json

from geotestlab.effect import (
    EffectEvidence,
    EffectScenario,
    assess_effect_plausibility,
)
from geotestlab.experiment import build_unified_result_summaries
from geotestlab.media import (
    DeliveryThresholds,
    ExperimentMediaScope,
    InputProvenance,
    MediaPlan,
    MediaValue,
    assess_media_delivery,
)
from geotestlab.recommendation import DesignScenario, assess_design_recommendation


class _TypedValue:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


def _recommendation_scenario() -> DesignScenario:
    return DesignScenario(
        scenario_id="candidate_a",
        size_metric=1.0,
        duration_periods=4,
        cost=100.0,
        match_status="supported",
        counterfactual_status="supported",
        power_status="supported",
        power_usable=True,
        power_meets_target=True,
        delivery_status="feasible",
        effect_status="evidence_backed",
        effect_meets_mde=True,
        region_constraints_status="valid",
    )


def test_unified_result_summaries_preserve_typed_stage_contracts():
    plan = MediaPlan(
        "meta_auction_social",
        values={
            "impressions": MediaValue(1000, InputProvenance.SUPPLIED_FORECAST),
        },
    )
    delivery = assess_media_delivery(
        plan,
        DeliveryThresholds(min_impressions=500),
        ExperimentMediaScope(excluded_from_experiment=("Excluded",)),
    )
    evidence = EffectEvidence(
        evidence_type="comparable_market_test",
        quality="high",
        source="prior study",
        scenarios=(
            EffectScenario("low", 2.0),
            EffectScenario("central", 5.0),
            EffectScenario("high", 8.0),
        ),
    )
    effect = assess_effect_plausibility(evidence, mde_pct=4.0)
    scenario = _recommendation_scenario()
    recommendation = assess_design_recommendation([scenario], "smallest_qualifying_design")

    summaries = build_unified_result_summaries(
        validation_results={
            "results": {"OLS": {"corr": 0.9, "counterfactual_reliability": "High"}}
        },
        bayesian_results={"uplift_pct": 4.0},
        power_result=_TypedValue({"mde": 3.0, "support_status": "supported"}),
        power_config=_TypedValue({"frequency": "weekly"}),
        media_delivery_result=delivery,
        media_delivery_plan=plan,
        media_delivery_thresholds=delivery.thresholds,
        media_delivery_scope=delivery.scope,
        effect_plausibility_result=effect,
        recommendation_result=recommendation,
        recommendation_scenarios=[scenario],
        recommendation_objective="smallest_qualifying_design",
    )

    assert set(summaries) == {
        "counterfactual_validation",
        "observed_impact",
        "statistical_power",
        "media_delivery",
        "effect_plausibility",
        "design_recommendation",
    }
    assert summaries["statistical_power"]["config"]["frequency"] == "weekly"
    assert summaries["media_delivery"]["plan"]["profile"]["profile_id"] == "meta_auction_social"
    assert summaries["media_delivery"]["scope"]["excluded_from_experiment"] == ["Excluded"]
    assert summaries["effect_plausibility"]["status"] == "evidence_backed"
    assert summaries["design_recommendation"]["scenarios"][0]["scenario_id"] == "candidate_a"
    assert summaries["design_recommendation"]["objective"] == "smallest_qualifying_design"
    json.dumps(summaries)
