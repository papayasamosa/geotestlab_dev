"""Write a KPI-pattern-format Excel workbook for testing.

The KPI pattern format is a wide DataFrame where:
    - Column 0: Region name
    - Columns 1..N: Time periods (Period_0 … Period_{N-1})

The first two regions share a near-identical pattern (small noise added)
to enable deterministic KPI-pattern matching tests.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def write_kpi_pattern_xlsx(
    path: str | Path,
    regions: list[str],
    n_periods: int = 52,
    seed: int = 42,
) -> Path:
    """Create a KPI-pattern-format Excel file at ``path``.

    Parameters
    ----------
    path : str or Path
        Output path.
    regions : list of str
        Region names.
    n_periods : int
        Number of time periods.
    seed : int
        Random seed.

    Notes
    -----
    The first two regions in ``regions`` share a near-identical pattern
    (``true_pattern + small_noise``).  The rest are random walks.
    """
    rng = np.random.default_rng(seed)
    true_pattern = rng.normal(100, 10, size=n_periods)

    rows: list[dict] = []
    for i, region in enumerate(regions):
        row: dict = {"Region": region}
        if i < 2:
            noise = rng.normal(0, 0.5, size=n_periods)
            values = true_pattern + noise
        else:
            values = rng.normal(100, 15, size=n_periods)
        for j in range(n_periods):
            row[f"Period_{j}"] = float(max(values[j], 0))
        rows.append(row)

    df = pd.DataFrame(rows)
    path = Path(path)
    df.to_excel(path, index=False, engine="openpyxl")
    return path
