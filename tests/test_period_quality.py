"""Unit tests for the pure tracking-outage detector in
geotestlab.data.period_quality — no Streamlit, no AppTest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.data.period_quality import (
    DEFINITE_OUTAGE,
    MISSING_PERIOD,
    NORMAL,
    POSSIBLE_OUTAGE,
    compute_period_quality,
)


def _wide(data: dict, regions: list[str], dates: list[str]) -> pd.DataFrame:
    """Build a region x date DataFrame from {date: [values in region order]}."""
    cols = {d: data[d] for d in dates}
    return pd.DataFrame(cols, index=regions)


def test_exact_market_wide_zero_is_definite_outage():
    regions = ["A", "B", "C", "D"]
    dates = ["d1", "d2"]
    wide = _wide({"d1": [0, 0, 0, 0], "d2": [10, 20, 30, 40]}, regions, dates)

    report = compute_period_quality(wide)

    assert report.definite_outage_dates == ("d1",)
    assert report.possible_outage_dates == ()
    assert report.missing_period_dates == ()
    row = next(r for r in report.rows if r.date == "d1")
    assert row.classification == DEFINITE_OUTAGE
    assert row.observed_regions == 4
    assert row.zero_regions == 4
    assert row.reasons  # a human-readable reason is recorded


def test_legitimate_nonzero_period_is_normal():
    regions = ["A", "B", "C"]
    dates = ["d1"]
    wide = _wide({"d1": [10, 20, 30]}, regions, dates)

    report = compute_period_quality(wide)

    assert report.rows[0].classification == NORMAL
    assert report.definite_outage_dates == ()


def test_partial_zero_is_flagged_possible_but_not_preselected():
    # 3 of 4 regions (75%) zero — below the 80% possible-outage default share.
    regions = ["A", "B", "C", "D"]
    wide = _wide({"d1": [0, 0, 0, 5]}, regions, ["d1"])
    report = compute_period_quality(wide)
    assert report.rows[0].classification == NORMAL

    # 4 of 5 regions (80%) zero — meets the possible-outage threshold, but
    # is NOT a "definite" (100%) zero, so it must not be preselected.
    regions5 = ["A", "B", "C", "D", "E"]
    wide5 = _wide({"d1": [0, 0, 0, 0, 5]}, regions5, ["d1"])
    report5 = compute_period_quality(wide5)
    assert report5.rows[0].classification == POSSIBLE_OUTAGE
    assert report5.possible_outage_dates == ("d1",)
    assert report5.definite_outage_dates == ()


def test_missing_market_wide_period_detected_separately_from_zero():
    regions = ["A", "B", "C", "D"]
    wide = _wide({"d1": [np.nan, np.nan, np.nan, 10]}, regions, ["d1"])

    report = compute_period_quality(wide)

    assert report.missing_period_dates == ("d1",)
    assert report.definite_outage_dates == ()
    row = report.rows[0]
    assert row.observed_regions == 1
    assert row.observation_coverage == 0.25


def test_all_missing_date_has_none_total_kpi_not_zero():
    regions = ["A", "B"]
    wide = _wide({"d1": [np.nan, np.nan]}, regions, ["d1"])

    report = compute_period_quality(wide)

    row = report.rows[0]
    assert row.total_kpi is None
    assert row.classification == MISSING_PERIOD


def test_definite_outage_requires_high_coverage():
    # Only 1 of 4 expected regions observed, and it's zero — this is a
    # missing-period problem (low coverage), not a "definite" all-zero flag,
    # even though the single observed region happens to be zero.
    regions = ["A", "B", "C", "D"]
    wide = _wide({"d1": [0, np.nan, np.nan, np.nan]}, regions, ["d1"])

    report = compute_period_quality(wide)

    assert report.rows[0].classification == MISSING_PERIOD
    assert report.definite_outage_dates == ()


def test_row_order_matches_input_column_order():
    regions = ["A", "B"]
    dates = ["d3", "d1", "d2"]
    wide = _wide({"d1": [1, 2], "d2": [3, 4], "d3": [5, 6]}, regions, dates)

    report = compute_period_quality(wide)

    assert [row.date for row in report.rows] == ["d3", "d1", "d2"]
