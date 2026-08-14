"""Tests for delivery-only calculations and feasibility semantics."""

from __future__ import annotations

from geotestlab.media import (
    DeliveryStatus,
    DeliveryThresholds,
    ExperimentMediaScope,
    MediaPlan,
    MediaValue,
    assess_media_delivery,
    delivery_result_is_stale,
)
from geotestlab.media.profiles import MediaField, PlatformProfile
from geotestlab.media.ui import _parse_weekly_pattern


def test_budget_cpm_frequency_and_audience_calculate_delivery_metrics():
    plan = MediaPlan(
        "meta_auction_social",
        values={
            "total_budget": MediaValue(1000, "analyst_assumption"),
            "cpm": MediaValue(10, "supplied_forecast", source="agency", source_date="2026-08-01"),
            "frequency": MediaValue(2, "analyst_assumption"),
            "eligible_audience": MediaValue(10000, "historical_observed"),
        },
    )

    result = assess_media_delivery(
        plan,
        DeliveryThresholds(min_impressions=90000, min_reach=4000, min_reach_percentage=40),
    )

    assert result.values["impressions"].value == 100000.0
    assert result.values["reach"].value == 50000.0
    assert result.values["reach_percentage"].value == 500.0
    assert result.calculated_fields == ("impressions", "reach", "reach_percentage")
    assert result.checks["impressions"]["passes"]
    assert "reach_percentage cannot exceed 100%" in result.blockers
    assert result.status is DeliveryStatus.BLOCKED


def test_delivery_is_incomplete_when_no_exposure_measure_is_available():
    result = assess_media_delivery(MediaPlan("meta_auction_social"))

    assert result.status is DeliveryStatus.INCOMPLETE
    assert result.missing_fields == ("impressions (or total budget plus CPM)",)


def test_threshold_failure_is_not_feasible_and_scope_is_explicit():
    plan = MediaPlan(
        "meta_auction_social",
        values={
            "impressions": MediaValue(1000, "historical_observed"),
            "reach": MediaValue(100, "historical_observed"),
        },
    )
    scope = ExperimentMediaScope(("Stockholm",), ordinary_media_allowed_in_excluded_regions=True)
    result = assess_media_delivery(plan, DeliveryThresholds(min_reach=500), scope)

    assert result.status is DeliveryStatus.NOT_FEASIBLE
    assert result.checks["reach"]["passes"] is False
    assert result.scope.to_dict()["excluded_from_experiment"] == ["Stockholm"]
    assert "ordinary media is allowed" in result.warnings[0]


def test_forecast_provenance_gaps_are_warnings_not_power_claims():
    plan = MediaPlan(
        "meta_auction_social",
        values={
            "impressions": MediaValue(1000, "supplied_forecast"),
        },
    )
    result = assess_media_delivery(plan)

    assert result.status is DeliveryStatus.FEASIBLE
    assert any("without a recorded source" in warning for warning in result.warnings)
    assert any("without a recorded source date" in warning for warning in result.warnings)
    assert all("power" not in warning.lower() for warning in result.warnings)


def test_delivery_result_becomes_stale_when_thresholds_change():
    plan = MediaPlan(
        "meta_auction_social",
        values={"impressions": MediaValue(1000, "historical_observed")},
    )
    result = assess_media_delivery(plan, DeliveryThresholds(min_impressions=500))

    assert not delivery_result_is_stale(result, plan, DeliveryThresholds(min_impressions=500))
    assert delivery_result_is_stale(result, plan, DeliveryThresholds(min_impressions=1500))


def test_thresholds_reject_invalid_percentages():
    try:
        DeliveryThresholds(min_reach_percentage=101)
    except ValueError as exc:
        assert "cannot exceed 100" in str(exc)
    else:
        raise AssertionError("invalid reach percentage threshold was accepted")


def test_scope_regions_are_normalized_for_reproducible_exports():
    scope = ExperimentMediaScope((" Stockholm ", "Oslo", "Stockholm"))

    assert scope.excluded_from_experiment == ("Oslo", "Stockholm")
    assert scope.to_dict()["excluded_from_experiment"] == ["Oslo", "Stockholm"]


def test_non_finite_weekly_budget_is_rejected_by_form_parser():
    pattern, error = _parse_weekly_pattern("1000, nan")

    assert pattern is None
    assert error == "Weekly budget pattern must contain only finite numbers."


def test_missing_threshold_observation_remains_incomplete():
    result = assess_media_delivery(
        MediaPlan("meta_auction_social"), DeliveryThresholds(min_impressions=100)
    )

    assert result.status is DeliveryStatus.INCOMPLETE
    assert result.checks["impressions"]["passes"] is None
    assert result.blockers == ()


def test_custom_profile_and_fields_survive_delivery_assessment_export():
    profile = PlatformProfile(
        profile_id="custom_social",
        display_name="Custom social",
        channel_family="auction_social",
        fields=(MediaField("impressions", "Impressions", "numeric"),),
    )
    plan = MediaPlan(
        "custom_social",
        values={"impressions": MediaValue(1000, "historical_observed")},
        custom_fields={"agency_model": MediaValue("v2", "analyst_assumption")},
    )

    result = assess_media_delivery(plan, profile=profile)

    assert result.status is DeliveryStatus.FEASIBLE
    assert result.to_dict()["custom_fields"]["agency_model"]["value"] == "v2"
    assert not delivery_result_is_stale(result, plan, profile=profile)
