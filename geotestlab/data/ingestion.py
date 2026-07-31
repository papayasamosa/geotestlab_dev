"""Production KPI ingestion: Excel parsing, layout detection, and long-format
reshape for the "simple" and "aggregated" KPI file formats.

This module must not import Streamlit. Callers (geotestmatch.py) are
responsible for turning the exceptions raised here into user-facing
messages and any st.stop() calls.
"""

from __future__ import annotations

import statistics
from datetime import datetime as _dt

import pandas as pd

from .exceptions import (
    MissingIdentifierColumnsError,
    NoRetainedKPIObservationsError,
    NoValidDateColumnsError,
    UnreadableWorkbookError,
    UnresolvedAggregationColumnError,
    UnresolvedMetricColumnError,
)
from .models import DataQualityReport, ParsedKPIData


def detect_date_columns(df_raw: pd.DataFrame) -> list:
    """
    Returns the columns in a raw uploaded KPI DataFrame that are real datetime column
    headers (as Excel produces when dates are used as column names), in their original
    order. Used to distinguish date/value columns from the leading identifier columns
    (region, metric, aggregation levels, etc.) in both the simple 2-column KPI file
    format and the newer multi-aggregation-level format.
    """
    return [c for c in df_raw.columns if isinstance(c, (pd.Timestamp, _dt))]


def detect_metric_column(non_date_cols) -> str | None:
    """Best-guess the metric-name column by header text ('Metric', case-insensitive).
    Returns None if no column matches, so callers can fall back to asking the user."""
    for c in non_date_cols:
        if isinstance(c, str) and c.strip().lower() == "metric":
            return c
    return None


def infer_frequency(dates) -> str:
    """Infer the dominant cadence of a date series: "daily", "weekly", or "unknown".

    Uses the median gap between sorted unique dates, matching the app's
    ``infer_time_series_frequency()`` semantics.  Pure helper — no Streamlit
    dependency.
    """
    try:
        unique_dates = sorted(
            pd.to_datetime(pd.Series(list(dates))).dropna().dt.normalize().unique()
        )
    except Exception:
        return "unknown"
    if len(unique_dates) < 2:
        return "unknown"
    diffs = [(b - a).days for a, b in zip(unique_dates, unique_dates[1:])]
    median_diff = statistics.median(diffs)
    if 0.5 <= median_diff <= 1.5:
        return "daily"
    if 5.5 <= median_diff <= 8.5:
        return "weekly"
    return "unknown"


def _expected_and_missing_dates(dates, frequency: str) -> tuple[int, tuple[pd.Timestamp, ...]]:
    """Return (expected_date_count, missing_dates) over the observed date range.

    For "daily" the expected grid is every calendar day in range; for "weekly"
    it is every period anchored on the weekday of the first observed date.  For
    an unknown frequency the observed dates are treated as the expected grid.
    """
    observed = pd.to_datetime(pd.Series(list(dates))).dropna().dt.normalize()
    observed_unique = observed.sort_values().unique()
    if len(observed_unique) == 0:
        return 0, ()
    first, last = observed_unique[0], observed_unique[-1]
    observed_set = set(observed_unique)

    if frequency == "daily":
        expected = pd.date_range(first, last, freq="D")
    elif frequency == "weekly":
        anchor = first.strftime("%a").upper()
        expected = pd.date_range(first, last, freq=f"W-{anchor}")
    else:
        expected = observed_unique

    expected_idx = pd.DatetimeIndex(expected)
    missing = tuple(d for d in expected_idx if d not in observed_set)
    return int(len(expected_idx)), missing


def _read_workbook(uploaded_file) -> pd.DataFrame:
    try:
        return pd.read_excel(uploaded_file, engine="calamine", header=0)
    except Exception:
        try:
            if hasattr(uploaded_file, "seek"):
                uploaded_file.seek(0)
            return pd.read_excel(uploaded_file, engine="openpyxl", header=0)
        except Exception as exc:
            raise UnreadableWorkbookError(
                "The KPI file could not be read with either the calamine or openpyxl "
                f"engine. (Details: {exc})"
            ) from exc


def load_and_reshape_kpi(uploaded_file, agg_col=None, metric_col=None) -> ParsedKPIData:
    """
    Load KPI Excel, melt to long format, keep missing values as NaN.

    Supports two file layouts, auto-detected from the number of non-date leading
    columns:
    - Simple (legacy): exactly 2 non-date columns — column 0 = region name, column 1
      = metric name. agg_col/metric_col are ignored in this case.
    - Aggregated (multiple aggregation levels): more than 2 non-date columns — e.g.
      column 0 = a raw key not used for matching (e.g. postcode), one or more middle
      columns = aggregation levels (e.g. TV Market, TV Region), one column = metric
      name. Requires agg_col and metric_col (selected via UI) to resolve which column
      is the region and which is the metric — raises UnresolvedAggregationColumnError /
      UnresolvedMetricColumnError if not supplied, so callers must detect this case
      first (via detect_date_columns()) and prompt for the selection before calling
      this function.

    Rows where the resolved region column is blank are dropped BEFORE melting, so
    unmapped/unclassified keys never silently inflate another region's totals.

    Returns a ParsedKPIData(data, quality) — `data` is byte-for-byte the same
    DataFrame the previous in-app implementation produced; `quality` is a
    DataQualityReport describing what was read, dropped, and retained.
    """
    df_raw = _read_workbook(uploaded_file)
    rows_read = len(df_raw)

    date_cols = detect_date_columns(df_raw)
    non_date_cols = [c for c in df_raw.columns if c not in date_cols]

    if len(non_date_cols) <= 2:
        if len(non_date_cols) < 2:
            raise MissingIdentifierColumnsError(
                "The file needs at least a region column and a metric column; "
                f"found {len(non_date_cols)} non-date column(s)."
            )
        parsed_layout = "simple"
        region_col = df_raw.columns[0]
        metric_col_resolved = df_raw.columns[1]
    else:
        parsed_layout = "aggregated"
        if agg_col is None:
            raise UnresolvedAggregationColumnError(
                "This file has more than one aggregation-level column; agg_col must "
                "be selected and passed in."
            )
        if metric_col is None:
            raise UnresolvedMetricColumnError(
                "This file has more than one aggregation-level column; metric_col "
                "must be selected and passed in."
            )
        region_col = agg_col
        metric_col_resolved = metric_col

    if not date_cols:
        raise NoValidDateColumnsError("No date columns were detected in the uploaded file.")

    blank_mask = df_raw[region_col].isna() | (df_raw[region_col].astype(str).str.strip() == "")
    blank_region_rows = int(blank_mask.sum())
    df_raw = df_raw[~blank_mask]

    raw_regions = tuple(sorted(df_raw[region_col].astype(str).str.strip().unique().tolist()))

    df_long = df_raw.melt(
        id_vars=[region_col, metric_col_resolved],
        value_vars=date_cols,
        var_name="date",
        value_name="kpi",
    )
    df_long = df_long.rename(columns={region_col: "region_raw", metric_col_resolved: "metric_name"})

    df_long["date"] = pd.to_datetime(df_long["date"], errors="coerce")
    invalid_date_values = int(df_long["date"].isna().sum())
    missing_kpi_blank = int(df_long["kpi"].isna().sum())

    # Drop rows with invalid date or missing KPI (do NOT fill with 0) — capture
    # the rejected rows first so they can be offered for download.
    _rejected_blank_or_invalid = df_long[df_long["date"].isna() | df_long["kpi"].isna()].copy()
    df_long = df_long.dropna(subset=["date", "kpi"])

    # Convert KPI to numeric, coercing errors -> NaN, then drop those rows
    df_long["kpi"] = pd.to_numeric(df_long["kpi"], errors="coerce")
    missing_kpi_non_numeric = int(df_long["kpi"].isna().sum())
    _rejected_non_numeric = df_long[df_long["kpi"].isna()].copy()
    df_long = df_long.dropna(subset=["kpi"])

    rejected_rows = (
        pd.concat([_rejected_blank_or_invalid, _rejected_non_numeric], ignore_index=True)
        if (len(_rejected_blank_or_invalid) or len(_rejected_non_numeric))
        else None
    )

    rows_retained = len(df_long)
    if rows_retained == 0:
        raise NoRetainedKPIObservationsError(
            "No KPI observations remain after removing invalid dates and missing/"
            "non-numeric KPI values."
        )

    _dup_mask = df_long.duplicated(subset=["region_raw", "metric_name", "date"], keep=False)
    duplicate_key_rows = int(_dup_mask.sum())
    duplicate_key_groups = int(
        df_long.loc[_dup_mask]
        .drop_duplicates(subset=["region_raw", "metric_name", "date"])
        .shape[0]
    )
    metrics_found = tuple(sorted(df_long["metric_name"].astype(str).unique().tolist()))

    # ---- Date coverage over the retained observations ----
    _retained_dates = pd.to_datetime(df_long["date"]).dropna().dt.normalize().sort_values()
    if len(_retained_dates):
        date_range = (_retained_dates.iloc[0], _retained_dates.iloc[-1])
    else:
        date_range = None
    inferred_frequency = infer_frequency(_retained_dates)
    expected_date_count, missing_dates = _expected_and_missing_dates(
        _retained_dates, inferred_frequency
    )

    # ---- Explicit, unambiguous counts ----
    observations_expected = len(df_raw) * len(date_cols)
    observations_removed = observations_expected - rows_retained
    source_rows_removed = blank_region_rows

    warnings: list[str] = []
    if blank_region_rows:
        warnings.append(f"{blank_region_rows} row(s) had a blank region and were dropped.")
    if duplicate_key_rows:
        warnings.append(
            f"{duplicate_key_rows} row(s) share a duplicate (region, metric, date) key."
        )

    quality = DataQualityReport(
        source_rows_read=rows_read,
        source_rows_dropped_blank_region=blank_region_rows,
        source_rows_removed=source_rows_removed,
        source_date_columns=len(date_cols),
        observations_expected=observations_expected,
        observations_retained=rows_retained,
        observations_dropped_missing_kpi=missing_kpi_blank,
        observations_dropped_non_numeric_kpi=missing_kpi_non_numeric,
        observations_dropped_invalid_date=invalid_date_values,
        observations_removed=observations_removed,
        duplicate_key_rows=duplicate_key_rows,
        duplicate_key_groups=duplicate_key_groups,
        selected_layout=parsed_layout,
        selected_aggregation_column=(str(agg_col) if agg_col is not None else None),
        selected_metric_column=str(metric_col_resolved),
        metrics_found=metrics_found,
        date_range=date_range,
        inferred_frequency=inferred_frequency,
        expected_date_count=expected_date_count,
        missing_dates=missing_dates,
        raw_regions=raw_regions,
        warnings=tuple(warnings),
        blocking_errors=(),
    )
    return ParsedKPIData(data=df_long, quality=quality, rejected_rows=rejected_rows)
