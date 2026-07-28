"""Pure period-level KPI quality detection (tracking-outage / missing-period flags).

Detects, per date, whether the data looks like a tracking outage rather than a
genuine business observation — without ever globally reinterpreting a zero KPI
value as missing. A KPI can legitimately be zero for some regions; this module
only flags a date as an outage candidate when the pattern across regions is
consistent with a tracking failure (most/all regions exactly zero, or most/all
regions missing).

This module must not import Streamlit. Callers turn a PeriodQualityReport into
UI (preselected multiselect options, warnings) and decide what to exclude.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DEFINITE_OUTAGE = "definite_market_wide_zero"
POSSIBLE_OUTAGE = "possible_widespread_outage"
MISSING_PERIOD = "missing_market_wide_period"
NORMAL = "normal"


@dataclass(frozen=True)
class PeriodQualityRow:
    date: pd.Timestamp
    total_kpi: float | None
    expected_regions: int
    observed_regions: int
    observation_coverage: float
    zero_regions: int
    zero_region_share: float
    classification: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PeriodQualityReport:
    rows: tuple[PeriodQualityRow, ...]
    definite_outage_dates: tuple[pd.Timestamp, ...]
    possible_outage_dates: tuple[pd.Timestamp, ...]
    missing_period_dates: tuple[pd.Timestamp, ...]


def compute_period_quality(
    wide: pd.DataFrame,
    *,
    min_coverage_for_definite: float = 0.9,
    possible_outage_zero_share: float = 0.8,
    missing_period_coverage_threshold: float = 0.5,
) -> PeriodQualityReport:
    """
    Classify each column (date) of a region-by-date KPI DataFrame.

    Args:
        wide: index = region, columns = date, values = KPI (NaN for a genuinely
            missing region/date observation — do not pre-fill NaN with 0).
        min_coverage_for_definite: minimum share of expected regions that must be
            observed (non-missing) for an all-zero date to be flagged as a
            "definite" market-wide zero rather than left unclassified.
        possible_outage_zero_share: share of *observed* regions that must be zero
            for a date to be flagged as a possible (not preselected) outage.
        missing_period_coverage_threshold: below this observation coverage, a
            date is flagged as a missing market-wide period rather than scored
            for zero share.

    Returns:
        PeriodQualityReport with one row per date column, in column order, plus
        convenience tuples of the dates in each actionable classification.
    """
    expected_regions = wide.shape[0]
    rows: list[PeriodQualityRow] = []
    definite_dates: list[pd.Timestamp] = []
    possible_dates: list[pd.Timestamp] = []
    missing_dates: list[pd.Timestamp] = []

    for date in wide.columns:
        col = wide[date]
        observed_mask = col.notna()
        observed_regions = int(observed_mask.sum())
        observation_coverage = observed_regions / expected_regions if expected_regions > 0 else 0.0
        zero_regions = int((col[observed_mask] == 0).sum())
        zero_region_share = zero_regions / observed_regions if observed_regions > 0 else 0.0
        total_kpi = float(col.sum(min_count=1)) if observed_regions > 0 else None

        reasons: list[str] = []
        if expected_regions > 0 and observation_coverage < missing_period_coverage_threshold:
            classification = MISSING_PERIOD
            reasons.append(
                f"only {observed_regions}/{expected_regions} regions observed "
                f"({observation_coverage:.0%} coverage)"
            )
            missing_dates.append(date)
        elif (
            observed_regions > 0
            and observation_coverage >= min_coverage_for_definite
            and zero_region_share >= 1.0
        ):
            classification = DEFINITE_OUTAGE
            reasons.append(
                f"all {observed_regions} observed regions are exactly zero "
                f"({observation_coverage:.0%} coverage)"
            )
            definite_dates.append(date)
        elif observed_regions > 0 and zero_region_share >= possible_outage_zero_share:
            classification = POSSIBLE_OUTAGE
            reasons.append(
                f"{zero_regions}/{observed_regions} observed regions "
                f"({zero_region_share:.0%}) are exactly zero"
            )
            possible_dates.append(date)
        else:
            classification = NORMAL

        rows.append(
            PeriodQualityRow(
                date=date,
                total_kpi=total_kpi,
                expected_regions=expected_regions,
                observed_regions=observed_regions,
                observation_coverage=observation_coverage,
                zero_regions=zero_regions,
                zero_region_share=zero_region_share,
                classification=classification,
                reasons=tuple(reasons),
            )
        )

    return PeriodQualityReport(
        rows=tuple(rows),
        definite_outage_dates=tuple(definite_dates),
        possible_outage_dates=tuple(possible_dates),
        missing_period_dates=tuple(missing_dates),
    )
