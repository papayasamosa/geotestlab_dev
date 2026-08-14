"""Tests for the generic platform-profile and media-plan contracts."""

from __future__ import annotations

from datetime import date

import pytest

from geotestlab.media import (
    InputProvenance,
    MediaField,
    MediaPlan,
    MediaValue,
    PlatformProfile,
    get_platform_profile,
    list_platform_profiles,
)


def test_meta_is_a_registered_generic_platform_profile():
    profile = get_platform_profile("meta_auction_social")

    assert profile.channel_family == "auction_social"
    assert {field.key for field in profile.fields} >= {
        "total_budget",
        "weekly_budget_pattern",
        "cpm",
        "impressions",
        "reach",
        "reach_percentage",
        "frequency",
        "eligible_audience",
        "campaign_objective",
        "optimisation_event",
        "targeting_restrictions",
        "geographic_targeting_method",
        "existing_activity_in_control",
        "spillover_contamination",
        "forecast_source",
        "forecast_date",
    }
    assert list_platform_profiles() == (profile,)


def test_media_value_retains_provenance_and_is_json_safe():
    value = MediaValue(
        value=date(2026, 8, 14),
        provenance=InputProvenance.SUPPLIED_FORECAST,
        source="agency forecast",
        source_date="2026-08-01",
    )

    assert value.to_dict() == {
        "value": "2026-08-14",
        "provenance": "supplied_forecast",
        "source": "agency forecast",
        "source_date": "2026-08-01",
        "notes": None,
    }


def test_media_plan_accepts_common_fields_and_custom_fields():
    plan = MediaPlan(
        profile_id="meta_auction_social",
        values={
            "total_budget": MediaValue(10000, "analyst_assumption"),
            "cpm": MediaValue(8.5, "supplied_forecast", source="Meta forecast"),
            "forecast_date": MediaValue("2026-08-01", "supplied_forecast"),
        },
        custom_fields={
            "agency_reach_model": MediaValue("v2", "analyst_assumption"),
        },
    )

    assert plan.validation_errors() == ()
    exported = plan.to_dict()
    assert exported["profile"]["profile_id"] == "meta_auction_social"
    assert exported["values"]["cpm"]["provenance"] == "supplied_forecast"
    assert exported["custom_fields"]["agency_reach_model"]["value"] == "v2"


def test_media_plan_surfaces_unknown_required_and_invalid_values():
    profile = PlatformProfile(
        profile_id="test_profile",
        display_name="Test profile",
        channel_family="test",
        fields=(MediaField("required_budget", "Required budget", "numeric", required=True),),
    )
    plan = MediaPlan(
        profile_id="test_profile",
        values={
            "unknown": MediaValue(1, "calculated"),
            "required_budget": MediaValue(-1, "calculated"),
        },
    )

    errors = plan.validation_errors(profile)
    assert "unknown field 'unknown' for profile 'test_profile'" in errors
    assert "required_budget must be non-negative" in errors
    assert "missing required field 'required_budget'" not in errors


def test_unordered_values_export_deterministically():
    profile_id = "meta_auction_social"
    first = MediaPlan(
        profile_id=profile_id,
        values={"targeting_restrictions": MediaValue({"age", "location"}, "analyst_assumption")},
    )
    second = MediaPlan(
        profile_id=profile_id,
        values={"targeting_restrictions": MediaValue({"location", "age"}, "analyst_assumption")},
    )

    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["values"]["targeting_restrictions"]["value"] == ["age", "location"]


def test_date_fields_reject_invalid_iso_strings():
    plan = MediaPlan(
        profile_id="meta_auction_social",
        values={"forecast_date": MediaValue("2026-02-30", "supplied_forecast")},
    )

    assert plan.validation_errors() == (
        "forecast_date must be a valid ISO date or datetime string",
    )


def test_plan_rejects_a_mismatched_explicit_profile():
    plan = MediaPlan(profile_id="meta_auction_social")
    other_profile = PlatformProfile(
        profile_id="other",
        display_name="Other",
        channel_family="other",
        fields=(),
    )

    with pytest.raises(ValueError, match="does not match"):
        plan.validation_errors(other_profile)
    with pytest.raises(ValueError, match="does not match"):
        plan.to_dict(other_profile)


def test_invalid_provenance_and_duplicate_profile_fields_are_rejected():
    with pytest.raises(ValueError, match="unknown media-input provenance"):
        MediaValue(1, "inferred")

    profile = get_platform_profile("meta_auction_social")
    plan = MediaPlan(
        profile_id=profile.profile_id,
        custom_fields={"cpm": MediaValue(1, "calculated")},
    )
    assert plan.validation_errors() == ("custom field 'cpm' duplicates a profile field",)
