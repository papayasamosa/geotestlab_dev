"""Write a simple-format KPI Excel workbook for testing.

The simple format has exactly 2 non-date columns:
    - Column 0: region name
    - Column 1: metric name

Remaining columns are date headers (datetime objects).

Edge cases supported:
    - blank region labels (dropped by the app)
    - unmapped region names
    - missing KPI values (NaN)
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_END_DATE = datetime.date(2026, 6, 28)


def write_simple_kpi_xlsx(
    path: str | Path,
    regions: list[str],
    metric_name: str = "Sales",
    n_weeks: int = 52,
    seed: int = 42,
    missing_rate: float = 0.0,
    end_date: datetime.date = DEFAULT_END_DATE,
    include_unmapped: bool = False,
    include_blank: bool = False,
) -> Path:
    """Create a simple-format KPI Excel file at ``path``.

    Each region gets a random-walk KPI series.

    Parameters
    ----------
    path : str or Path
        Output path for the .xlsx file.
    regions : list of str
        Region names to include.
    metric_name : str
        Metric identifier.
    n_weeks : int
        Number of weekly periods.
    seed : int
        Random seed for reproducibility.
    missing_rate : float
        Fraction of KPI values to set to NaN.
    end_date : datetime.date
        Last date in the series.
    include_unmapped : bool
        If True, add a region named ``_UnmappedRegion`` that won't match
        any geography-level region list.
    include_blank : bool
        If True, add a row with a blank region label.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end_date, periods=n_weeks, freq="W")

    rows: list[dict] = []
    for region in regions:
        base = rng.uniform(80, 120)
        trend = rng.uniform(-0.05, 0.05)
        noise = rng.normal(0, 2, size=n_weeks)
        values = base + trend * np.arange(n_weeks) + noise
        row: dict = {"Region": region, "Metric": metric_name}
        for i, d in enumerate(dates):
            kpi_val = float(max(values[i], 0))
            if missing_rate > 0 and rng.random() < missing_rate:
                kpi_val = np.nan
            row[d] = kpi_val
        rows.append(row)

    if include_unmapped:
        row = {"Region": "_UnmappedRegion", "Metric": metric_name}
        for i, d in enumerate(dates):
            row[d] = float(max(rng.normal(100, 10), 0))
        rows.append(row)

    if include_blank:
        row = {"Region": "", "Metric": metric_name}
        for i, d in enumerate(dates):
            row[d] = float(max(rng.normal(100, 10), 0))
        rows.append(row)

    df = pd.DataFrame(rows)
    path = Path(path)
    df.to_excel(path, index=False, engine="openpyxl")
    return path
