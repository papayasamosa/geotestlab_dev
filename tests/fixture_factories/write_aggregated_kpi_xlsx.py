"""Write an aggregated-format KPI Excel workbook for testing.

The aggregated format has MORE than 2 non-date columns:
    - Column 0: raw key (e.g. postcode / store ID)
    - One or more middle columns: aggregation levels (e.g. TV Market, TV Region)
    - Column N-1: metric name

The user selects which aggregation column is the region and which is the metric
via the UI (agg_col, metric_col).

Edge cases supported:
    - blank aggregation labels
    - unmapped region names
    - duplicate region-date combinations
    - missing KPI values
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_END_DATE = datetime.date(2026, 6, 28)


def write_aggregated_kpi_xlsx(
    path: str | Path,
    regions: list[str],
    aggregation_level_col: str = "TV Region",
    raw_key_col: str = "Store ID",
    metric_name: str = "Sales",
    n_weeks: int = 52,
    seed: int = 42,
    missing_rate: float = 0.0,
    end_date: datetime.date = DEFAULT_END_DATE,
    include_blank_agg: bool = False,
    include_duplicates: bool = False,
) -> Path:
    """Create an aggregated-format KPI Excel file at ``path``.

    Parameters
    ----------
    path : str or Path
        Output path.
    regions : list of str
        Region names (used as aggregation-level values).
    aggregation_level_col : str
        Name of the column containing the region/aggregation label.
    raw_key_col : str
        Name of the raw-key column (e.g. Store ID).
    metric_name : str
        Metric identifier.
    n_weeks : int
        Number of weekly periods.
    seed : int
        Random seed.
    missing_rate : float
        Fraction of KPI values to set to NaN.
    end_date : datetime.date
        Last date in the series.
    include_blank_agg : bool
        If True, add a row with a blank aggregation label.
    include_duplicates : bool
        If True, duplicate one region-date combination.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end_date, periods=n_weeks, freq="W")

    rows: list[dict] = []
    for region in regions:
        # Each region gets a few raw keys
        n_keys = rng.integers(1, 4)
        for ki in range(n_keys):
            store_id = f"{region}_Store_{ki}"
            base = rng.uniform(80, 120)
            trend = rng.uniform(-0.05, 0.05)
            noise = rng.normal(0, 2, size=n_weeks)
            values = base + trend * np.arange(n_weeks) + noise
            row: dict = {
                raw_key_col: store_id,
                aggregation_level_col: region,
                "Metric": metric_name,
                "Sub-Region": f"{region}_Sub",  # extra aggregation column
            }
            for i, d in enumerate(dates):
                kpi_val = float(max(values[i], 0))
                if missing_rate > 0 and rng.random() < missing_rate:
                    kpi_val = np.nan
                row[d] = kpi_val
            rows.append(row)

            if include_duplicates and ki == 0:
                # Duplicate the region's first week values for the first key
                dup_row = dict(row)
                dup_row[raw_key_col] = f"{store_id}_DUP"
                rows.append(dup_row)

    if include_blank_agg:
        row = {
            raw_key_col: "BlankStore",
            aggregation_level_col: "",
            "Metric": metric_name,
            "Sub-Region": "",
        }
        for i, d in enumerate(dates):
            row[d] = float(max(rng.normal(100, 10), 0))
        rows.append(row)

    df = pd.DataFrame(rows)
    path = Path(path)
    df.to_excel(path, index=False, engine="openpyxl")
    return path
