"""Focused coverage for the media-delivery UI's pure helpers."""

from __future__ import annotations

import geotestlab.media.ui as media_ui


def test_preset_weekly_amounts_even_splits_budget_equally():
    amounts = media_ui._preset_weekly_amounts("Even", 1000.0, 4)
    assert amounts == [250.0, 250.0, 250.0, 250.0]
    assert sum(amounts) == 1000.0


def test_preset_weekly_amounts_front_loaded_decreases_each_week():
    amounts = media_ui._preset_weekly_amounts("Front-loaded", 1000.0, 4)
    assert amounts == sorted(amounts, reverse=True)
    assert sum(amounts) == 1000.0


def test_preset_weekly_amounts_back_loaded_increases_each_week():
    amounts = media_ui._preset_weekly_amounts("Back-loaded", 1000.0, 4)
    assert amounts == sorted(amounts)
    assert sum(amounts) == 1000.0


def test_preset_weekly_amounts_zero_budget_is_empty():
    assert media_ui._preset_weekly_amounts("Even", 0.0, 4) == []


def test_preset_weekly_amounts_zero_weeks_is_empty():
    assert media_ui._preset_weekly_amounts("Even", 1000.0, 0) == []


def test_preset_weekly_amounts_unknown_pattern_is_empty():
    assert media_ui._preset_weekly_amounts("Unknown", 1000.0, 4) == []


def test_preset_amounts_feed_the_existing_weekly_pattern_parser():
    """The preset amounts must parse cleanly through the untouched, existing
    comma-separated parser — confirms the new controls didn't change that
    contract, just how the string reaching it gets built."""
    amounts = media_ui._preset_weekly_amounts("Even", 900.0, 3)
    weekly_pattern_text = ", ".join(str(amount) for amount in amounts)
    parsed, error = media_ui._parse_weekly_pattern(weekly_pattern_text)
    assert error is None
    assert parsed == {"week_1": 300.0, "week_2": 300.0, "week_3": 300.0}
