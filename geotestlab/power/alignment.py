"""Date-keyed alignment for regional KPI series (power-spike correction).

The spike previously column-stacked independently sorted regional arrays, which
silently misaligns controls when regions have missing, duplicated or shuffled
dates. This module builds a single date-keyed matrix and reports:

- dates expected, dates retained, dates removed;
- controls with missing dates;
- duplicate region-date keys;
- continuity of the expected date grid.
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
        evaluation workflow in ``geotestlab.validation.matrix``).
    control_regions : sequence
        Control regions (one column each).
    expected_dates : sequence, optional
        The expected date grid. Defaults to the sorted dates present in the
        frame.

    Returns
    -------
    test : pandas.Series
        Aggregated test KPI indexed by date (NaN where a date is missing).
    controls : pandas.DataFrame
        Control KPI indexed by date (one column per control, NaN where missing).
    diagnostics : dict
        JSON-safe alignment diagnostics.
    """
    diag: dict = {}

    duplicates = df[df.duplicated(subset=["region", "date"], keep=False)]
    diag["duplicate_region_date_keys"] = int(df.duplicated(subset=["region", "date"]).sum())
    diag["duplicate_region_date_examples"] = [
        f"{row.region}@{row.date}" for row in duplicates.head(5).itertuples()
    ]

    # Pivot without raising on duplicate keys (first wins; duplicates are
    # reported above so no data is silently discarded).
    piv = df.pivot_table(index="date", columns="region", values="kpi", aggfunc="first")
    piv.index = pd.to_datetime(piv.index)

    if expected_dates is not None:
        expected = pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(list(expected_dates)))))
    else:
        expected = pd.DatetimeIndex(sorted(piv.index))

    test_cols = [r for r in test_regions if r in piv.columns]
    if not test_cols:
        test_raw = pd.Series(index=piv.index, dtype=float)
    elif len(test_cols) == 1:
        test_raw = pd.to_numeric(piv[test_cols[0]], errors="coerce")
    else:
        # Sum over test regions per date (skipna matches the evaluation
        # workflow's groupby().sum(), which sums the available regions).
        test_raw = piv[test_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
    test = test_raw.reindex(expected)

    diag["dates_expected"] = int(len(expected))
    diag["dates_retained"] = int(test.notna().sum())
    diag["dates_removed"] = int(test.isna().sum())

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
