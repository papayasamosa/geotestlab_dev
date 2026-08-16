"""Every internal status/enum value must have an explicit analyst-facing label.

These tests walk the real enum classes (not a copy of their members), so a
new enum value added anywhere in ``geotestlab/`` without a matching entry in
``geotestlab/ui/labels.py`` fails loudly here instead of leaking raw
implementation text into the UI later.
"""

from __future__ import annotations

import pytest

from geotestlab.data.models import MarketSizeMeasure
from geotestlab.effect.plausibility import (
    _EFFECT_DIRECTIONS,
    EffectPlausibilityStatus,
    EvidenceQuality,
    EvidenceType,
)
from geotestlab.experiment.stages import STAGE_STATUSES
from geotestlab.media.delivery import DeliveryStatus
from geotestlab.media.profiles import InputProvenance
from geotestlab.power.methods import FALLBACK_FIT_METHOD, FIT_METHOD_NAMES
from geotestlab.recommendation.recommendation import RecommendationObjective, RecommendationStatus
from geotestlab.ui.labels import (
    DELIVERY_STATUS_LABELS,
    EFFECT_DIRECTION_LABELS,
    EFFECT_PLAUSIBILITY_STATUS_LABELS,
    EVIDENCE_QUALITY_LABELS,
    EVIDENCE_TYPE_LABELS,
    FIT_METHOD_LABELS,
    INPUT_PROVENANCE_LABELS,
    MARKET_SIZE_MEASURE_LABELS,
    RECOMMENDATION_OBJECTIVE_LABELS,
    RECOMMENDATION_STATUS_LABELS,
    STAGE_STATUS_LABELS,
    display_label,
    format_date_range,
    format_percent,
)


def test_every_stage_status_has_a_label():
    for status in STAGE_STATUSES:
        assert status in STAGE_STATUS_LABELS, f"missing stage-status label for {status!r}"


def test_every_effect_direction_has_a_label():
    for direction in _EFFECT_DIRECTIONS:
        assert direction in EFFECT_DIRECTION_LABELS, (
            f"missing effect-direction label for {direction!r}"
        )


def test_every_evidence_type_has_a_label():
    for member in EvidenceType:
        assert member.value in EVIDENCE_TYPE_LABELS, f"missing evidence-type label for {member!r}"


def test_every_evidence_quality_has_a_label():
    for member in EvidenceQuality:
        assert member.value in EVIDENCE_QUALITY_LABELS, (
            f"missing evidence-quality label for {member!r}"
        )


def test_every_effect_plausibility_status_has_a_label():
    for member in EffectPlausibilityStatus:
        assert member.value in EFFECT_PLAUSIBILITY_STATUS_LABELS, (
            f"missing effect-plausibility-status label for {member!r}"
        )


def test_every_delivery_status_has_a_label():
    for member in DeliveryStatus:
        assert member.value in DELIVERY_STATUS_LABELS, (
            f"missing delivery-status label for {member!r}"
        )


def test_every_input_provenance_has_a_label():
    for member in InputProvenance:
        assert member.value in INPUT_PROVENANCE_LABELS, (
            f"missing input-provenance label for {member!r}"
        )


def test_every_recommendation_objective_has_a_label():
    for member in RecommendationObjective:
        assert member.value in RECOMMENDATION_OBJECTIVE_LABELS, (
            f"missing recommendation-objective label for {member!r}"
        )


def test_every_recommendation_status_has_a_label():
    for member in RecommendationStatus:
        assert member.value in RECOMMENDATION_STATUS_LABELS, (
            f"missing recommendation-status label for {member!r}"
        )


def test_every_market_size_measure_has_a_label():
    for member in MarketSizeMeasure:
        assert member.value in MARKET_SIZE_MEASURE_LABELS, (
            f"missing market-size-measure label for {member!r}"
        )


def test_every_fit_method_has_a_label():
    for name in (*FIT_METHOD_NAMES, FALLBACK_FIT_METHOD):
        assert name in FIT_METHOD_LABELS, f"missing fit-method label for {name!r}"


def test_display_label_translates_an_enum_member():
    assert display_label("delivery_status", DeliveryStatus.NOT_FEASIBLE) == "Not suitable"


def test_display_label_translates_a_plain_string():
    assert display_label("stage_status", "stale") == "Inputs changed"


def test_display_label_none_falls_back_to_not_set():
    assert display_label("stage_status", None) == "Not set"


def test_display_label_none_uses_explicit_default():
    assert display_label("stage_status", None, default="Unavailable") == "Unavailable"


def test_display_label_unmapped_value_is_humanised_not_crashed():
    assert display_label("stage_status", "some_new_status") == "Some new status"


def test_display_label_unmapped_value_uses_explicit_default():
    assert display_label("stage_status", "some_new_status", default="Unavailable") == "Unavailable"


def test_display_label_unknown_kind_raises():
    with pytest.raises(KeyError):
        display_label("not_a_real_kind", "value")


def test_effect_plausibility_and_evidence_quality_disagree_on_unknown():
    # The same raw string ("unknown") means different things in different
    # domains, which is exactly why display_label is scoped by kind rather
    # than using one flat lookup table.
    assert display_label("evidence_quality", "unknown") == "Unknown"
    assert display_label("effect_plausibility_status", "unknown") == "Not checked yet"


def test_format_percent_none_is_an_em_dash():
    assert format_percent(None) == "—"


def test_format_percent_formats_a_fraction_to_one_decimal_by_default():
    assert format_percent(0.052) == "5.2%"


def test_format_percent_respects_decimals():
    assert format_percent(0.05, decimals=0) == "5%"


def test_format_date_range_none_is_an_em_dash():
    assert format_date_range(None, None) == "—"


def test_format_date_range_formats_both_ends():
    from datetime import date

    assert format_date_range(date(2025, 1, 5), date(2025, 3, 12)) == "05 Jan 2025 – 12 Mar 2025"
