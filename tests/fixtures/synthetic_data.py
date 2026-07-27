"""Synthetic data fixtures for GeoTestLab characterisation tests.

These fixtures generate DataFrames that mimic the structure of the bundled
demographic workbook and KPI upload files.  No real data is used, and the
generation logic is deterministic (seeded random) so tests are reproducible.

Each generator function documents:
    - columns produced
    - region names
    - date ranges
    - intended edge case
    - whether randomness is involved
"""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np
import pandas as pd

# Shared RNG for deterministic generation — seeds are fixed per function.
_RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Synthetic demographic / structural data
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "Population",
    "Population Density",
    "Female",
    "Male",
    "Age U16",
    "Age 16-24",
    "Age 25-34",
    "Age 35-49",
    "Age 50-64",
    "Age 65+",
    "Social Grade AB",
    "Social Grade C1",
    "Social Grade C2",
    "Social Grade DE",
    "Median Income",
]

# Proportion features (values 0-1) that are displayed as percentages.
PROPORTION_FEATURES: set[str] = {
    "Female",
    "Male",
    "Age U16",
    "Age 16-24",
    "Age 25-34",
    "Age 35-49",
    "Age 50-64",
    "Age 65+",
    "Social Grade AB",
    "Social Grade C1",
    "Social Grade C2",
    "Social Grade DE",
}

# Core numeric features (not proportions).
NUMERIC_FEATURES: set[str] = {"Population", "Population Density", "Median Income"}


def synthetic_demographic_data(
    n_regions: int = 16,
    seed: int = 42,
) -> pd.DataFrame:
    """Create a synthetic demographic DataFrame mimicking the bundled workbook.

    Produces ``n_regions`` rows with columns matching the app's expected
    feature set.  Proportion features sum to 1 across complementary pairs
    (e.g. Female + Male = 1).

    Parameters
    ----------
    n_regions : int
        Number of synthetic regions (default 16 — small enough for exhaustive
        brute-force matching checks).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    pd.DataFrame
        Columns: ``Region``, ``Population``, ``Population Density``, all age
        bands, all social grades, ``Median Income``.
    """
    rng = np.random.default_rng(seed)

    region_names = [f"Region_{i:02d}" for i in range(n_regions)]

    population = rng.integers(50_000, 5_000_000, size=n_regions).astype(float)
    pop_density = rng.uniform(10, 5_000, size=n_regions)
    median_income = rng.uniform(20_000, 80_000, size=n_regions)

    # Proportion features — generate and normalise complementary pairs.
    female = rng.uniform(0.45, 0.55, size=n_regions)
    male = 1.0 - female

    age_u16 = rng.uniform(0.12, 0.25, size=n_regions)
    age_16_24 = rng.uniform(0.08, 0.18, size=n_regions)
    age_25_34 = rng.uniform(0.12, 0.22, size=n_regions)
    age_35_49 = rng.uniform(0.15, 0.25, size=n_regions)
    age_50_64 = rng.uniform(0.10, 0.20, size=n_regions)
    age_65plus = 1.0 - (age_u16 + age_16_24 + age_25_34 + age_35_49 + age_50_64)
    age_65plus = np.clip(age_65plus, 0.05, 0.30)

    sg_ab = rng.uniform(0.15, 0.35, size=n_regions)
    sg_c1 = rng.uniform(0.15, 0.30, size=n_regions)
    sg_c2 = rng.uniform(0.10, 0.25, size=n_regions)
    sg_de = 1.0 - (sg_ab + sg_c1 + sg_c2)
    sg_de = np.clip(sg_de, 0.05, 0.35)

    df = pd.DataFrame(
        {
            "Region": region_names,
            "Population": population,
            "Population Density": pop_density,
            "Female": female,
            "Male": male,
            "Age U16": age_u16,
            "Age 16-24": age_16_24,
            "Age 25-34": age_25_34,
            "Age 35-49": age_35_49,
            "Age 50-64": age_50_64,
            "Age 65+": age_65plus,
            "Social Grade AB": sg_ab,
            "Social Grade C1": sg_c1,
            "Social Grade C2": sg_c2,
            "Social Grade DE": sg_de,
            "Median Income": median_income,
        }
    )
    return df


def synthetic_kpi_data(
    regions: list[str],
    n_weeks: int = 52,
    seed: int = 42,
    metric_name: str = "Sales",
    missing_rate: float = 0.0,
) -> pd.DataFrame:
    """Create a synthetic weekly KPI DataFrame in long format.

    Each region-week gets a KPI value drawn from a region-specific random walk
    with noise.  Useful for testing validation and Bayesian flows.

    Parameters
    ----------
    regions : list of str
        Region names.
    n_weeks : int
        Number of weekly observations (default 52).
    seed : int
        Random seed.
    metric_name : str
        Label for the metric column.
    missing_rate : float
        Fraction of KPI values to set to NaN (0.0 = no missing).

    Returns
    -------
    pd.DataFrame
        Columns: ``date``, ``region_raw``, ``metric_name``, ``kpi``.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(
        end=datetime.date.today(),
        periods=n_weeks,
        freq="W",
    )
    rows: list[dict[str, Any]] = []
    for region in regions:
        base = rng.uniform(80, 120)
        trend = rng.uniform(-0.05, 0.05)
        noise = rng.normal(0, 2, size=n_weeks)
        values = base + trend * np.arange(n_weeks) + noise
        for i, d in enumerate(dates):
            kpi_val = float(max(values[i], 0))  # no negative KPI
            if missing_rate > 0 and rng.random() < missing_rate:
                kpi_val = np.nan
            rows.append(
                {
                    "date": d,
                    "region_raw": region,
                    "metric_name": metric_name,
                    "kpi": kpi_val,
                }
            )
    return pd.DataFrame(rows)


def synthetic_daily_kpi_data(
    regions: list[str],
    n_days: int = 365,
    seed: int = 42,
    metric_name: str = "Sales",
    missing_rate: float = 0.0,
) -> pd.DataFrame:
    """Create a synthetic daily KPI DataFrame in long format.

    Same pattern as ``synthetic_kpi_data`` but with daily frequency.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(
        end=datetime.date.today(),
        periods=n_days,
        freq="D",
    )
    rows: list[dict[str, Any]] = []
    for region in regions:
        base = rng.uniform(80, 120)
        trend = rng.uniform(-0.02, 0.02)
        noise = rng.normal(0, 5, size=n_days)
        values = base + trend * np.arange(n_days) + noise
        for i, d in enumerate(dates):
            kpi_val = float(max(values[i], 0))
            if missing_rate > 0 and rng.random() < missing_rate:
                kpi_val = np.nan
            rows.append(
                {
                    "date": d,
                    "region_raw": region,
                    "metric_name": metric_name,
                    "kpi": kpi_val,
                }
            )
    return pd.DataFrame(rows)


def synthetic_kpi_pattern_data(
    regions: list[str],
    n_periods: int = 52,
    seed: int = 42,
) -> pd.DataFrame:
    """Create KPI-pattern data for pattern matching.

    Generates a wide-format DataFrame where each column is a time period,
    mimicking the KPI Pattern upload format.  Two regions share a near-identical
    pattern (small noise), the rest are random.

    Returns
    -------
    pd.DataFrame
        Columns: ``Region``, ``Period_0`` … ``Period_{n_periods-1}``.
    """
    rng = np.random.default_rng(seed)
    true_pattern = rng.normal(100, 10, size=n_periods)

    rows: list[dict[str, Any]] = []
    for i, region in enumerate(regions):
        row: dict[str, Any] = {"Region": region}
        if i < 2:
            # Nearly identical pattern for first two regions
            noise = rng.normal(0, 0.5, size=n_periods)
            values = true_pattern + noise
        else:
            values = rng.normal(100, 15, size=n_periods)
        for j in range(n_periods):
            row[f"Period_{j}"] = float(max(values[j], 0))
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helper: subset features for quick tests
# ---------------------------------------------------------------------------

DEFAULT_TEST_FEATURES = [
    "Population",
    "Population Density",
    "Median Income",
    "Female",
    "Male",
    "Age 25-34",
    "Social Grade AB",
]
