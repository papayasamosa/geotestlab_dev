"""KPI-pattern matching feature preparation.

The KPI-pattern "distance" is computed over a region's *shape* rather than its
raw KPI volume: each region's weekly series is indexed to its own mean = 100
over the selected range, and those indexed weekly values become the matching
features.  This module provides the pure preparation steps (filtering, numeric
coercion, wide aggregation, retention, indexing-to-100, and the match-ready
``agg_df`` build).  The live app keeps a cached wrapper around
``read_kpi_pattern_excel`` and calls the pure functions from its UI flow.

No Streamlit import.
"""

from __future__ import annotations

import io

import pandas as pd

from geotestlab.data.regional import RegionalKPIDataset, regional_kpi_to_wide

from .models import POPULATION_COL


def read_kpi_pattern_excel(file_bytes: bytes) -> pd.DataFrame:
    """Parse the uploaded KPI Pattern workbook (pure; the app caches on the raw bytes)."""
    bio = io.BytesIO(file_bytes)
    try:
        return pd.read_excel(bio, engine="calamine", header=0)
    except Exception:
        bio.seek(0)
        return pd.read_excel(bio, engine="openpyxl", header=0)


def filter_kpi_rows(df: pd.DataFrame, metric_col: str, metric_value, agg_col: str):
    """Keep only rows for the selected metric with a non-blank aggregation level.

    Returns ``(filtered, n_dropped)`` where ``n_dropped`` counts rows removed
    because the aggregation-level cell was blank — unmapped/unclassified raw
    keys must never silently inflate another region's total.
    """
    filtered = df[df[metric_col] == metric_value].copy()
    n_before = len(filtered)
    filtered = filtered.dropna(subset=[agg_col])
    filtered = filtered[filtered[agg_col].astype(str).str.strip() != ""]
    return filtered, n_before - len(filtered)


def coerce_kpi_date_values(df: pd.DataFrame, date_cols: list) -> tuple[pd.DataFrame, int]:
    """Coerce date columns to numeric before aggregating.

    A non-numeric cell becomes missing (and is counted in ``n_non_numeric_cells``)
    rather than silently raising or being dropped by groupby/sum.
    """
    raw_values = df[date_cols]
    numeric_values = raw_values.apply(pd.to_numeric, errors="coerce")
    n_non_numeric = int(numeric_values.isna().sum().sum() - raw_values.isna().sum().sum())
    out = df.copy()
    out[date_cols] = numeric_values
    return out, n_non_numeric


def build_kpi_pattern_wide(filtered: pd.DataFrame, agg_col: str, date_cols: list) -> pd.DataFrame:
    """Aggregate filtered rows to wide (region x date) form.

    ``sum(min_count=1)`` keeps an aggregation-level/date group where every
    contributing row is missing as missing, instead of a real-looking 0.
    """
    return filtered.groupby(agg_col)[date_cols].sum(min_count=1)


def build_kpi_pattern_wide_from_regional(
    dataset: RegionalKPIDataset,
    metric_value: str,
    date_cols: list,
) -> pd.DataFrame:
    """Build the KPI Pattern wide series from the canonical regional dataset."""

    return regional_kpi_to_wide(dataset, metric_value=metric_value, dates=date_cols)


def retain_kpi_dates(wide_full: pd.DataFrame, retained_dates: list):
    """Restrict the wide frame to retained dates and drop unusable regions.

    Returns ``(wide_retained, incomplete_regions)``.  Regions that are all-NaN
    across the retained dates are dropped, then all-zero regions are dropped
    (they cannot be indexed to 100).
    """
    wide = wide_full[retained_dates]
    wide = wide.dropna(how="all")
    incomplete_regions = sorted(wide[wide.isna().any(axis=1)].index)
    wide = wide[wide.sum(axis=1, min_count=1) > 0]
    return wide, incomplete_regions


def index_kpi_series_to_100(wide: pd.DataFrame) -> pd.DataFrame:
    """Index each region to its own mean over the selected range = 100.

    This is what makes "distance" comparable across regions of very different
    raw KPI volume: matching runs on the *pattern*, not the volume.  Regions
    with any NaN after indexing are dropped (a NaN shape cannot be scored).
    """
    row_means = wide.mean(axis=1)
    indexed = wide.div(row_means, axis=0) * 100
    indexed = indexed.dropna(how="any")
    return indexed


def build_kpi_pattern_agg_df(
    indexed_wide: pd.DataFrame,
    wide_raw: pd.DataFrame,
    geo_col: str,
    active_features: list[str],
    population_col: str = POPULATION_COL,
) -> pd.DataFrame:
    """Build the match-ready ``agg_df`` from the indexed wide frame.

    Columns become ``[geo_col] + active_features`` (one ``wk_YYYYMMDD`` feature
    per retained date).  ``population_col`` is aliased to mean "total KPI volume
    over the selected range" rather than population — that is what
    "Test/Control Population Share" measures throughout the matching UI; user
    facing labels are adjusted where they would otherwise say "population".
    """
    agg_df = indexed_wide.reset_index()
    agg_df.columns = [geo_col] + active_features
    agg_df[population_col] = [wide_raw.loc[r].sum() for r in indexed_wide.index]
    return agg_df
