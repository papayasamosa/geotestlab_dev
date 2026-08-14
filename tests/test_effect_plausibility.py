"""Tests for evidence-aware effect-plausibility scenarios."""

from __future__ import annotations

import pytest

from geotestlab.effect import (
    EffectEvidence,
    EffectPlausibilityStatus,
    EffectScenario,
    assess_effect_plausibility,
    effect_result_is_stale,
)


def _evidence(**overrides) -> EffectEvidence:
    values = {
        "evidence_type": "prior_same_market_platform_geo_test",
        "quality": "medium",
        "source": "experiment-2025-07",
        "source_date": "2025-08-01",
        "scenarios": (
            EffectScenario("low", 2.0),
            EffectScenario("central", 5.0),
            EffectScenario("high", 9.0),
        ),
    }
    values.update(overrides)
    return EffectEvidence(**values)


def test_no_evidence_reports_unknown_without_a_recommendation():
    result = assess_effect_plausibility(None, mde_pct=6.0, delivery_status="feasible")

    assert result.status is EffectPlausibilityStatus.UNKNOWN
    assert result.comparisons == ()
    assert "effect plausibility is unknown" in result.warnings[0]


def test_evidence_scenarios_compare_with_mde_and_retain_separate_delivery_status():
    evidence = _evidence()
    result = assess_effect_plausibility(
        evidence, mde_pct=6.0, delivery_status="not_feasible", delivery_fingerprint="abc"
    )

    assert result.status is EffectPlausibilityStatus.EVIDENCE_BACKED
    assert [comparison.meets_mde for comparison in result.comparisons] == [False, False, True]
    assert result.comparisons[1].margin_to_mde_pct == -1.0
    assert any("not_feasible" in warning for warning in result.warnings)
    assert result.to_dict()["evidence"]["source"] == "experiment-2025-07"


def test_one_sided_direction_rejects_an_opposite_signed_effect():
    positive = assess_effect_plausibility(
        _evidence(), mde_pct=5.0, effect_direction="one_sided_negative"
    )

    assert [comparison.meets_mde for comparison in positive.comparisons] == [False, False, False]
    negative = _evidence(
        scenarios=(
            EffectScenario("low", -9.0),
            EffectScenario("central", -5.0),
            EffectScenario("high", -2.0),
        )
    )
    result = assess_effect_plausibility(
        negative, mde_pct=5.0, effect_direction="one_sided_negative"
    )
    assert [comparison.meets_mde for comparison in result.comparisons] == [True, True, False]


def test_analyst_scenarios_are_conditional_and_icpa_carries_uncertainty_warning():
    evidence = _evidence(evidence_type="incremental_cpa", quality="low")
    result = assess_effect_plausibility(evidence, mde_pct=5.0)

    assert result.status is EffectPlausibilityStatus.EVIDENCE_BACKED
    assert any("assumption bridge" in warning for warning in result.warnings)

    analyst = _evidence(evidence_type="analyst_assumption", quality="low")
    assert assess_effect_plausibility(analyst).status is EffectPlausibilityStatus.CONDITIONAL
    assert (
        assess_effect_plausibility(_evidence(quality="unknown")).status
        is EffectPlausibilityStatus.CONDITIONAL
    )


def test_adjusted_evidence_cannot_silently_become_central():
    result = assess_effect_plausibility(_evidence(adjusted=True), mde_pct=5.0)

    assert result.status is EffectPlausibilityStatus.BLOCKED
    assert "cannot be used as the central scenario" in result.blockers[0]

    approved = assess_effect_plausibility(
        _evidence(adjusted=True, central_approved=True), mde_pct=5.0
    )
    assert approved.status is EffectPlausibilityStatus.EVIDENCE_BACKED
    assert any("explicit approval" in warning for warning in approved.warnings)


def test_effect_result_staleness_tracks_mde_and_evidence():
    evidence = _evidence()
    result = assess_effect_plausibility(evidence, mde_pct=5.0)

    assert not effect_result_is_stale(result, evidence, 5.0)
    assert effect_result_is_stale(result, evidence, 6.0)


def test_evidence_requires_source_and_ordered_scenarios():
    with pytest.raises(ValueError, match="source must not be empty"):
        _evidence(source="")
    with pytest.raises(ValueError, match="ordered exactly"):
        _evidence(
            scenarios=(
                EffectScenario("central", 2.0),
                EffectScenario("low", 5.0),
                EffectScenario("high", 9.0),
            )
        )
    with pytest.raises(ValueError, match="source_date"):
        _evidence(source_date="2026-02-30")
