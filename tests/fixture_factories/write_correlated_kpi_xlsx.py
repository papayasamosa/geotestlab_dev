"""Write a simple-format KPI Excel workbook where test and control regions
share a common underlying pattern plus independent noise.

Unlike write_simple_kpi_xlsx (independent per-region random walks, suited to
testing the ingestion/parsing layer), this generates data with a genuine,
strong linear relationship between the test region and its controls — the
regime that time-series validation (ElasticNetCV / rolling-origin / placebo)
actually assumes. Independent-walk data sits at a near-zero-coefficient
knife-edge where ElasticNetCV's coefficient selection becomes sensitive to
tiny floating-point/ordering differences (observed directly: the same
scenario driven twice picked 2 vs 0 non-zero coefficients). Sharing a common
pattern keeps the fit's qualitative outcome (which features are retained)
stable and reproducible for golden-file characterisation.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_END_DATE = datetime.date(2026, 6, 28)


def write_correlated_kpi_xlsx(
    path: str | Path,
    test_region: str,
    control_regions: list[str],
    metric_name: str = "Sales",
    n_periods: int = 60,
    freq: str = "W",
    seed: int = 42,
    base_level: float = 100.0,
    pattern_noise_scale: float = 8.0,
    region_noise_scale: float = 3.0,
    end_date: datetime.date = DEFAULT_END_DATE,
) -> Path:
    """Create a simple-format KPI Excel file at ``path`` where every region's
    series is ``shared_pattern + independent per-region noise``.

    Parameters
    ----------
    freq : str
        pandas date_range frequency — "W" for weekly, "D" for daily.
    pattern_noise_scale : float
        Standard deviation of the shared pattern's own random walk — controls
        how much genuine signal there is to fit against.
    region_noise_scale : float
        Standard deviation of each region's independent noise on top of the
        shared pattern — smaller relative to pattern_noise_scale means a
        stronger, more clearly non-zero fit.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=end_date, periods=n_periods, freq=freq)
    shared_pattern = base_level + rng.normal(0, pattern_noise_scale, size=n_periods).cumsum() * 0.1

    rows: list[dict] = []
    for region in [test_region] + list(control_regions):
        values = shared_pattern + rng.normal(0, region_noise_scale, size=n_periods)
        row: dict = {"Region": region, "Metric": metric_name}
        for i, d in enumerate(dates):
            row[d] = float(max(values[i], 0))
        rows.append(row)

    df = pd.DataFrame(rows)
    path = Path(path)
    df.to_excel(path, index=False, engine="openpyxl")
    return path
