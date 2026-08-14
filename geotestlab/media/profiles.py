"""Generic platform-profile and media-plan contracts.

The profile schema is intentionally declarative.  A profile describes which
delivery fields a platform exposes and how those fields should be labelled;
it does not calculate delivery or make claims about incremental KPI impact.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from numbers import Real
from typing import Any, Mapping

MEDIA_PLAN_SCHEMA_VERSION = "media-plan/v1"
PLATFORM_PROFILE_SCHEMA_VERSION = "platform-profile/v1"


class InputProvenance(StrEnum):
    """How a media-plan value entered the workflow."""

    SUPPLIED_FORECAST = "supplied_forecast"
    CALCULATED = "calculated"
    HISTORICAL_OBSERVED = "historical_observed"
    ANALYST_ASSUMPTION = "analyst_assumption"


INPUT_PROVENANCES = tuple(item.value for item in InputProvenance)


def _json_value(value: Any) -> Any:
    """Convert common analyst-entered values into deterministic JSON values."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda x: str(x[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_json_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


@dataclass(frozen=True)
class MediaValue:
    """A value plus the provenance needed to interpret it safely."""

    value: Any
    provenance: InputProvenance | str
    source: str | None = None
    source_date: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        try:
            provenance = InputProvenance(self.provenance)
        except ValueError as exc:
            raise ValueError(
                f"unknown media-input provenance {self.provenance!r}; "
                f"expected one of {INPUT_PROVENANCES}"
            ) from exc
        object.__setattr__(self, "provenance", provenance)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe value with provenance retained."""

        return {
            "value": _json_value(self.value),
            "provenance": self.provenance.value,
            "source": self.source,
            "source_date": self.source_date,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MediaField:
    """Declarative metadata for one platform-specific or common field."""

    key: str
    label: str
    value_type: str = "any"
    unit: str | None = None
    required: bool = False
    description: str = ""

    def validate(self, value: Any) -> str | None:
        """Return a validation message, or ``None`` when the value is valid."""

        if self.value_type == "numeric":
            if isinstance(value, bool) or not isinstance(value, Real):
                return f"{self.key} must be numeric"
            if not math.isfinite(float(value)):
                return f"{self.key} must be finite"
            if float(value) < 0:
                return f"{self.key} must be non-negative"
        elif self.value_type == "text" and not isinstance(value, str):
            return f"{self.key} must be text"
        elif self.value_type == "date":
            if not isinstance(value, (date, datetime, str)):
                return f"{self.key} must be a date or ISO date string"
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return f"{self.key} must be a valid ISO date or datetime string"
        elif self.value_type == "list" and (
            isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset))
        ):
            return f"{self.key} must be a list-like value"
        elif self.value_type == "mapping" and not isinstance(value, Mapping):
            return f"{self.key} must be a mapping"
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return schema metadata suitable for a dynamic form or export."""

        return {
            "key": self.key,
            "label": self.label,
            "value_type": self.value_type,
            "unit": self.unit,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class PlatformProfile:
    """A reusable platform schema; no statistical assumptions are embedded."""

    profile_id: str
    display_name: str
    channel_family: str
    fields: tuple[MediaField, ...]
    schema_version: str = PLATFORM_PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("platform profile id must not be empty")
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError(f"platform profile {self.profile_id!r} contains duplicate field keys")

    @property
    def field_map(self) -> dict[str, MediaField]:
        """Return field metadata indexed by stable key."""

        return {field.key: field for field in self.fields}

    def to_dict(self) -> dict[str, Any]:
        """Return the declarative profile schema for UI/export consumers."""

        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "channel_family": self.channel_family,
            "fields": [field.to_dict() for field in self.fields],
        }


@dataclass(frozen=True)
class MediaPlan:
    """A profile-bound set of media inputs, including custom fields."""

    profile_id: str
    values: Mapping[str, MediaValue] = field(default_factory=dict)
    custom_fields: Mapping[str, MediaValue] = field(default_factory=dict)

    def _selected_profile(self, profile: PlatformProfile | None) -> PlatformProfile:
        """Resolve a profile and reject mismatched plan/profile identities."""

        selected_profile = profile or get_platform_profile(self.profile_id)
        if selected_profile.profile_id != self.profile_id:
            raise ValueError(
                f"profile id {selected_profile.profile_id!r} does not match "
                f"media plan profile id {self.profile_id!r}"
            )
        return selected_profile

    def validation_errors(self, profile: PlatformProfile | None = None) -> tuple[str, ...]:
        """Validate field names, required values, types and provenance metadata."""

        selected_profile = self._selected_profile(profile)
        field_map = selected_profile.field_map
        errors: list[str] = []
        for key, media_value in self.values.items():
            if key not in field_map:
                errors.append(f"unknown field {key!r} for profile {self.profile_id!r}")
                continue
            if not isinstance(media_value, MediaValue):
                errors.append(f"{key} must use MediaValue so provenance is retained")
                continue
            message = field_map[key].validate(media_value.value)
            if message:
                errors.append(message)
        for key, field_spec in field_map.items():
            if field_spec.required and key not in self.values:
                errors.append(f"missing required field {key!r}")
        for key, media_value in self.custom_fields.items():
            if key in field_map:
                errors.append(f"custom field {key!r} duplicates a profile field")
            elif not isinstance(media_value, MediaValue):
                errors.append(f"custom field {key} must use MediaValue")
        return tuple(errors)

    def to_dict(self, profile: PlatformProfile | None = None) -> dict[str, Any]:
        """Return a reproducible export preserving profile and provenance."""

        selected_profile = self._selected_profile(profile)
        return {
            "schema_version": MEDIA_PLAN_SCHEMA_VERSION,
            "profile": selected_profile.to_dict(),
            "values": {key: self.values[key].to_dict() for key in sorted(self.values)},
            "custom_fields": {
                key: self.custom_fields[key].to_dict() for key in sorted(self.custom_fields)
            },
        }


_COMMON_FIELDS = (
    MediaField("total_budget", "Total budget", "numeric", "currency"),
    MediaField(
        "weekly_budget_pattern",
        "Weekly budget pattern",
        "mapping",
        description="Budget by planned week.",
    ),
    MediaField("cpm", "CPM", "numeric", "currency per 1,000 impressions"),
    MediaField("impressions", "Impressions", "numeric", "impressions"),
    MediaField("reach", "Reach", "numeric", "people or accounts"),
    MediaField("reach_percentage", "Reach percentage", "numeric", "%"),
    MediaField("frequency", "Frequency", "numeric", "average exposures"),
    MediaField("eligible_audience", "Eligible audience", "numeric", "people or accounts"),
    MediaField("campaign_objective", "Campaign objective", "text"),
    MediaField("optimisation_event", "Optimisation event", "text"),
    MediaField("targeting_restrictions", "Targeting restrictions", "list"),
    MediaField("geographic_targeting_method", "Geographic targeting method", "text"),
    MediaField("existing_activity_in_control", "Existing activity in control", "text"),
    MediaField("spillover_contamination", "Spillover or contamination", "text"),
    MediaField("forecast_source", "Forecast source", "text"),
    MediaField("forecast_date", "Forecast date", "date"),
)


PLATFORM_PROFILES: dict[str, PlatformProfile] = {
    "meta_auction_social": PlatformProfile(
        profile_id="meta_auction_social",
        display_name="Meta (auction social)",
        channel_family="auction_social",
        fields=_COMMON_FIELDS,
    ),
}


def get_platform_profile(profile_id: str) -> PlatformProfile:
    """Return a registered profile or raise an actionable error."""

    try:
        return PLATFORM_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"unknown platform profile {profile_id!r}; expected one of {tuple(PLATFORM_PROFILES)}"
        ) from exc


def list_platform_profiles() -> tuple[PlatformProfile, ...]:
    """Return registered profiles in deterministic order."""

    return tuple(PLATFORM_PROFILES[key] for key in sorted(PLATFORM_PROFILES))
