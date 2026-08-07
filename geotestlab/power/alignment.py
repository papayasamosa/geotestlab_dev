"""Date-keyed alignment for regional KPI series (power-spike correction).

The spike previously column-stacked independently sorted regional arrays, which
silently misaligns controls when regions have missing, duplicated or shuffled
dates. This module builds a single date-keyed matrix and reports:

- dates expected, dates retained (test aggregate available), dates removed;
- controls with missing dates, and which selected region(s) are missing on
  each affected date (test and control, separately);
- duplicate region-date keys among the SELECTED regions (test + control) --
  these BLOCK the analysis (``duplicate_keys_blocking``) rather than being
  silently resolved by row order, because letting arbitrary pivot row order
  decide an analytical value is unacceptable;
- continuity of the expected date grid.

Selected test-region composition is fixed: the test aggregate for a date
requires EVERY selected test region to have a value that date (``min_count``
equal to the full requested test-region count), not merely "whichever are
available". A date where some but not all selected test regions report is
therefore excluded, not silently rebased onto a smaller test aggregate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_date_keyed_matrix(df, test_regions, control_regions, expected_dates=None):
    """Build a date-keyed test series and control matrix from a long frame.

    Parameters
    ----------
    df : pandas.DataFrame
        Long frame with columns ``date``, ``region``, ``kpi``.
    test_regions : sequence
        Test regions, aggregated by summing KPI per date (matching the
        evaluation workflow in ``geotestlab.validation.matrix``), but only on
        dates where EVERY selected test region reports a value -- partial
        test-region presence does not silently rebase the test aggregate onto
        a smaller effective composition.
    control_regions : sequence
        Control regions (one column each).
    expected_dates : sequence, optional
        The expected date grid. Defaults to the sorted dates present in the
        frame.

    Returns
    -------
    test : pandas.Series
        Aggregated test KPI indexed by date (NaN where a date is missing or
        the selected test-region composition is incomplete that date).
    controls : pandas.DataFrame
        Control KPI indexed by date (one column per control, NaN where missing).
    diagnostics : dict
        JSON-safe alignment diagnostics.
    """
    diag: dict = {}

    selected_regions = set(test_regions) | set(control_regions)
    selected_df = df[df["region"].isin(selected_regions)]
    duplicates = selected_df[selected_df.duplicated(subset=["region", "date"], keep=False)]
    diag["duplicate_region_date_keys"] = int(
        selected_df.duplicated(subset=["region", "date"]).sum()
    )
    diag["duplicate_region_date_examples"] = [
        f"{row.region}@{row.date}" for row in duplicates.head(5).itertuples()
    ]
    # Duplicate keys among the SELECTED regions must block the analysis, not
    # be silently resolved by whichever row happens to come first in the
    # input order. The pivot below still uses aggfunc="first" so a matrix can
    # be built at all, but that value is NEVER treated as the analytical
    # answer: callers must check duplicate_keys_blocking and refuse to
    # produce a completed result when it is True.
    diag["duplicate_keys_blocking"] = diag["duplicate_region_date_keys"] > 0

    # Pivot without raising on duplicate keys (first wins for matrix shape
    # only; see duplicate_keys_blocking above). dropna=False keeps all-NaN
    # rows/columns so tracking outages (a date where EVERY region is missing)
    # are reported as removed dates instead of silently vanishing.
    piv = df.pivot_table(
        index="date", columns="region", values="kpi", aggfunc="first", dropna=False
    )
    piv.index = pd.to_datetime(piv.index)

    if expected_dates is not None:
        expected = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(list(expected_dates)))))
    else:
        expected = pd.DatetimeIndex(sorted(piv.index))

    # Fixed test-region composition: build one column per SELECTED test
    # region (NaN for a region absent from the data entirely), then require
    # EVERY column to be present (min_count == number of selected test
    # regions) for the aggregate to count. A date where some but not all
    # selected test regions report is excluded, never silently summed over
    # whichever subset happened to be available that date.
    test_block = pd.DataFrame(index=piv.index)
    for r in test_regions:
        test_block[r] = pd.to_numeric(piv[r], errors="coerce") if r in piv.columns else np.nan
    if test_block.shape[1] == 0:
        test_raw = pd.Series(index=piv.index, dtype=float)
    else:
        test_raw = test_block.sum(axis=1, min_count=test_block.shape[1])
    test = test_raw.reindex(expected)

    diag["dates_expected"] = int(len(expected))
    diag["dates_retained"] = int(test.notna().sum())
    diag["dates_removed"] = int(test.isna().sum())

    test_block_expected = test_block.reindex(expected)
    missing_test_mask = test_block_expected.isna()
    diag["missing_test_regions_by_date"] = {
        str(pd.Timestamp(d).date()): [r for r in test_regions if bool(missing_test_mask.loc[d, r])]
        for d in test_block_expected.index[missing_test_mask.any(axis=1)]
    }

    controls = pd.DataFrame(index=expected)
    missing = {}
    for r in control_regions:
        if r in piv.columns:
            s = pd.to_numeric(piv[r], errors="coerce").reindex(expected)
        else:
            s = pd.Series(index=expected, dtype=float)
        controls[r] = s.to_numpy()
        missing[r] = int(s.isna().sum())
    diag["controls_with_missing_dates"] = {str(r): int(v) for r, v in missing.items()}

    missing_control_mask = controls.isna()
    diag["missing_control_regions_by_date"] = {
        str(pd.Timestamp(d).date()): [
            r for r in control_regions if bool(missing_control_mask.loc[d, r])
        ]
        for d in controls.index[missing_control_mask.any(axis=1)]
    }

    diag["continuity"] = _continuity(expected)
    return test, controls, diag


def _continuity(expected):
    if len(expected) <= 1:
        return "single_date"
    diffs = np.asarray((expected[1:] - expected[:-1]) / np.timedelta64(1, "D"), dtype=float)
    med = float(np.median(diffs))
    if med <= 0:
        return "non_increasing"
    gaps = int(np.sum(diffs > med * 1.5))
    return "contiguous" if gaps == 0 else f"{gaps} gap(s)"
