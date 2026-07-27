"""Write a daily-frequency simple-format KPI Excel workbook for testing.

Same 2-non-date-column layout as write_simple_kpi_xlsx (Region, Metric, then
one column per date), but with consecutive daily dates instead of weekly —
used to characterise the app's "Daily" time-series frequency mode.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_END_DATE = datetime.date(2026, 6, 28)


def write_daily_kpi_xlsx(
    path: str | Path,
    regions: list[str],
    metric_name: str = "Sales",
    n_days: int = 120,
    seed: int = 42,
    missing_rate: float = 0.0,
    end_date: datetime.date = DEFAULT_END_DATE,
) -> Path:
    """Create a daily-frequency simple-format KPI Excel file at ``path``.

    Parameters mirror write_simple_kpi_xlsx, with ``n_days`` consecutive
    calendar-day dates (freq="D") instead of ``n_weeks`` weekly dates.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end_date, periods=n_days, freq="D")

    rows: list[dict] = []
    for region in regions:
        base = rng.uniform(80, 120)
        trend = rng.uniform(-0.01, 0.01)
        noise = rng.normal(0, 2, size=n_days)
        values = base + trend * np.arange(n_days) + noise
        row: dict = {"Region": region, "Metric": metric_name}
        for i, d in enumerate(dates):
            kpi_val = float(max(values[i], 0))
            if missing_rate > 0 and rng.random() < missing_rate:
                kpi_val = np.nan
            row[d] = kpi_val
        rows.append(row)

    df = pd.DataFrame(rows)
    path = Path(path)
    df.to_excel(path, index=False, engine="openpyxl")
    return path
