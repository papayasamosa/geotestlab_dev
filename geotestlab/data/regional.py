"""Canonical regional KPI preparation.

This module is the shared data contract for KPI Pattern matching, historical
validation, and future test-sizing/power work.  It accepts the two existing
wide Excel layouts, preserves missing observations as missing, and aggregates
raw rows to one ``(region, metric, date)`` analytical key.

The legacy ingestion adapter deliberately remains available: it exposes the
old unaggregated, non-missing long frame used by the current validation UI.
New consumers should use :class:`RegionalKPIDataset` instead.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date as _date
from datetime import datetime as _dt
from functools import reduce
from math import gcd
from typing import Any

import pandas as pd

from .exceptions import (
    MissingIdentifierColumnsError,
    NoValidDateColumnsError,
    UnresolvedAggregationColumnError,
    UnresolvedMetricColumnError,
)
from .models import DataQualityReport, MarketSizeMeasure

_SOURCE_ROW_COLUMN = "source_row_position"


def detect_date_columns(df_raw: pd.DataFrame) -> list:
    """Return date-like column headers in their original order."""

    date_columns = []
    for column in df_raw.columns:
        if isinstance(column, (pd.Timestamp, _dt, _date)):
            date_columns.append(column)
            continue
        if isinstance(column, str):
            text = column.strip()
            looks_date_like = len(text) >= 6 and any(character.isdigit() for character in text)
            if looks_date_like and not pd.isna(pd.to_datetime(text, errors="coerce")):
                date_columns.append(column)
    return date_columns


def detect_metric_column(non_date_cols) -> str | None:
    """Find the conventional case-insensitive ``Metric`` column, if present."""

    for column in non_date_cols:
        if isinstance(column, str) and column.strip().lower() == "metric":
            return column
    return None


def infer_frequency(dates) -> str:
    """Infer daily, weekly, or unknown cadence from a date sequence."""

    try:
        unique_dates = sorted(
            pd.to_datetime(pd.Series(list(dates))).dropna().dt.normalize().unique()
        )
    except Exception:
        return "unknown"
    if len(unique_dates) < 2:
        return "unknown"
    diffs = [(b - a).days for a, b in zip(unique_dates, unique_dates[1:])]
    median_diff = float(pd.Series(diffs).median())
    # A single missing weekly period produces gaps such as [14, 7], for
    # which the median is 10.5 and the old heuristic incorrectly lost the
    # weekly cadence. The greatest common divisor is robust to those integer
    # multiples while retaining ``unknown`` for irregular gaps.
    base_diff = reduce(gcd, (int(diff) for diff in diffs))
    cadence = float(base_diff) if base_diff > 0 else median_diff
    if 0.5 <= cadence <= 1.5:
        return "daily"
    if 5.5 <= cadence <= 8.5:
        return "weekly"
    return "unknown"


def expected_and_missing_dates(dates, frequency: str) -> tuple[int, tuple[pd.Timestamp, ...]]:
    """Return the expected count and missing dates over the observed range."""

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


def source_data_fingerprint(df_raw: pd.DataFrame) -> str:
    """Create a deterministic, row-order-invariant fingerprint of source data."""

    column_order = sorted(
        range(len(df_raw.columns)),
        key=lambda index: (type(df_raw.columns[index]).__name__, str(df_raw.columns[index])),
    )
    frame = df_raw.iloc[:, column_order].copy()
    columns = [df_raw.columns[index] for index in column_order]
    labels = [f"{type(column).__name__}:{column!s}" for column in columns]
    try:
        row_hashes = pd.util.hash_pandas_object(frame, index=False).astype("uint64")
    except (TypeError, ValueError):
        row_hashes = pd.util.hash_pandas_object(frame.astype(str), index=False).astype("uint64")
    payload = {
        "columns": labels,
        "dtypes": [str(frame[column].dtype) for column in frame.columns],
        "rows": sorted(int(value) for value in row_hashes.tolist()),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _clean_label(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


@dataclass(frozen=True)
class RegionalKPIConfig:
    """Input selections for canonical regional KPI preparation."""

    aggregation_column: str | None = None
    metric_column: str | None = None
    metric_value: str | None = None
    market_size_measure: MarketSizeMeasure = MarketSizeMeasure.HISTORICAL_KPI_VOLUME

    def __post_init__(self) -> None:
        if not isinstance(self.market_size_measure, MarketSizeMeasure):
            try:
                object.__setattr__(
                    self,
                    "market_size_measure",
                    MarketSizeMeasure(self.market_size_measure),
                )
            except ValueError as exc:
                raise ValueError(
                    f"Unsupported market_size_measure: {self.market_size_measure!r}"
                ) from exc


@dataclass(frozen=True)
class RegionalKPIDataset:
    """Canonical regional KPI data plus source, quality, and provenance metadata."""

    data: pd.DataFrame
    config: RegionalKPIConfig
    quality: DataQualityReport
    source_data_fingerprint: str
    provenance: pd.DataFrame
    source_observations: pd.DataFrame
    legacy_data: pd.DataFrame
    rejected_rows: pd.DataFrame | None = None

    @property
    def metrics(self) -> tuple[str, ...]:
        return tuple(sorted(self.data["metric"].dropna().astype(str).unique().tolist()))

    def for_metric(self, metric_value: str) -> RegionalKPIDataset:
        """Return a view of this dataset restricted to one metric."""

        metric = str(metric_value)
        if metric not in self.metrics:
            raise ValueError(f"Metric {metric_value!r} is not present in the KPI dataset.")
        return replace(
            self,
            data=self.data[self.data["metric"].astype(str) == metric].copy(),
            source_observations=self.source_observations[
                self.source_observations["metric"].astype(str) == metric
            ].copy(),
            provenance=self.provenance[self.provenance["metric"].astype(str) == metric].copy(),
            config=replace(self.config, metric_value=metric),
        )

    def market_size_weights(
        self,
        metric_value: str | None = None,
        measure: MarketSizeMeasure | None = None,
    ) -> pd.Series:
        """Return regional weights using an explicit market-size measure.

        Historical KPI volume is the only measure derivable from this source
        contract. Population and custom weights must be supplied by a separate
        typed source; they are never inferred from the number of regions.
        """

        selected_measure = measure or self.config.market_size_measure
        if not isinstance(selected_measure, MarketSizeMeasure):
            selected_measure = MarketSizeMeasure(selected_measure)
        if selected_measure is not MarketSizeMeasure.HISTORICAL_KPI_VOLUME:
            raise ValueError(
                f"{selected_measure.value} weights are not present in a RegionalKPIDataset; "
                "supply them explicitly rather than deriving them from region counts."
            )
        frame = self.data
        if metric_value is not None:
            frame = frame[frame["metric"].astype(str) == str(metric_value)]
        return frame.groupby("region", sort=True)["kpi"].sum(min_count=1)


def regional_kpi_to_wide(
    dataset: RegionalKPIDataset,
    metric_value: str | None = None,
    dates: list | tuple | None = None,
) -> pd.DataFrame:
    """Adapt canonical data to the region-by-date shape used by matching."""

    frame = dataset.data
    if metric_value is not None:
        frame = frame[frame["metric"].astype(str) == str(metric_value)]
    if frame.empty:
        return pd.DataFrame(index=pd.Index([], name="region"))
    wide = frame.pivot(index="region", columns="date", values="kpi")
    if dates is not None:
        wide = wide.reindex(columns=list(dates))
    return wide.sort_index(axis=0).sort_index(axis=1)


def regional_kpi_to_validation_frame(
    dataset: RegionalKPIDataset, metric_value: str | None = None
) -> pd.DataFrame:
    """Adapt canonical data to the validation service's long input shape."""

    frame = dataset.data
    if metric_value is not None:
        frame = frame[frame["metric"].astype(str) == str(metric_value)]
    return frame[["region", "date", "kpi"]].copy().sort_values(["region", "date"], kind="mergesort")


def _resolve_layout(
    df_raw: pd.DataFrame, config: RegionalKPIConfig, date_cols: list
) -> tuple[str, str, str]:
    non_date_cols = [column for column in df_raw.columns if column not in date_cols]
    if len(non_date_cols) < 2:
        raise MissingIdentifierColumnsError(
            "The file needs at least a region column and a metric column; "
            f"found {len(non_date_cols)} non-date column(s)."
        )
    if len(non_date_cols) <= 2:
        return "simple", str(non_date_cols[0]), str(non_date_cols[1])
    if config.aggregation_column is None:
        raise UnresolvedAggregationColumnError(
            "This file has more than one aggregation-level column; agg_col must be selected."
        )
    if config.metric_column is None:
        raise UnresolvedMetricColumnError(
            "This file has more than one aggregation-level column; metric_col must be selected."
        )
    if config.aggregation_column not in non_date_cols:
        raise UnresolvedAggregationColumnError(
            f"Selected aggregation column {config.aggregation_column!r} is not in the file."
        )
    if config.metric_column not in non_date_cols:
        raise UnresolvedMetricColumnError(
            f"Selected metric column {config.metric_column!r} is not in the file."
        )
    if config.aggregation_column == config.metric_column:
        raise ValueError("aggregation_column and metric_column must be different columns.")
    return "aggregated", config.aggregation_column, config.metric_column


def prepare_regional_kpi(
    df_raw: pd.DataFrame, config: RegionalKPIConfig | None = None
) -> RegionalKPIDataset:
    """Prepare one canonical regional KPI dataset from a wide source frame."""

    config = config or RegionalKPIConfig()
    frame = df_raw.copy()
    fingerprint = source_data_fingerprint(frame)
    date_cols = detect_date_columns(frame)
    if not date_cols:
        raise NoValidDateColumnsError("No date columns were detected in the uploaded file.")
    layout, region_col, metric_col = _resolve_layout(frame, config, date_cols)

    frame[_SOURCE_ROW_COLUMN] = range(len(frame))
    blank_region_mask = frame[region_col].isna() | (frame[region_col].astype(str).str.strip() == "")
    blank_region_rows = int(blank_region_mask.sum())
    frame = frame.loc[~blank_region_mask].copy()
    raw_regions = tuple(sorted(frame[region_col].map(_clean_label).unique().tolist()))

    non_date_cols = [column for column in df_raw.columns if column not in date_cols]
    melted = frame.melt(
        id_vars=[*non_date_cols, _SOURCE_ROW_COLUMN],
        value_vars=date_cols,
        var_name="date",
        value_name="kpi_raw",
    )
    melted["date"] = pd.to_datetime(melted["date"], errors="coerce").dt.normalize()
    melted["kpi"] = pd.to_numeric(melted["kpi_raw"], errors="coerce")
    melted["region"] = melted[region_col].map(_clean_label)
    melted["metric"] = melted[metric_col].map(_clean_label)

    invalid_date_mask = melted["date"].isna()
    missing_kpi_mask = melted["kpi_raw"].isna()
    valid_date_mask = ~invalid_date_mask
    non_numeric_mask = valid_date_mask & ~missing_kpi_mask & melted["kpi"].isna()
    legacy_mask = valid_date_mask & ~melted["kpi"].isna()

    rejected_blank_or_invalid = melted.loc[
        invalid_date_mask | missing_kpi_mask,
        ["region", "metric", "date", "kpi_raw", _SOURCE_ROW_COLUMN],
    ].rename(columns={"kpi_raw": "kpi"})
    rejected_non_numeric = melted.loc[
        non_numeric_mask,
        ["region", "metric", "date", "kpi_raw", _SOURCE_ROW_COLUMN],
    ].rename(columns={"kpi_raw": "kpi"})
    rejected_rows = (
        pd.concat([rejected_blank_or_invalid, rejected_non_numeric], ignore_index=True)
        if len(rejected_blank_or_invalid) or len(rejected_non_numeric)
        else None
    )

    selected_mask = pd.Series(True, index=melted.index)
    if config.metric_value is not None:
        selected_mask &= melted["metric"].eq(str(config.metric_value))
    canonical_source = melted.loc[valid_date_mask & selected_mask].copy()
    source_observations = canonical_source[
        ["region", "metric", "date", "kpi", _SOURCE_ROW_COLUMN]
    ].copy()
    source_observations["region_raw"] = source_observations["region"]
    source_observations["metric_name"] = source_observations["metric"]
    source_observations["selected_aggregation"] = region_col
    source_observations["source_data_fingerprint"] = fingerprint

    group_cols = ["region", "metric", "date"]
    aggregated = (
        canonical_source.groupby(group_cols, sort=True, dropna=False)
        .agg(kpi=("kpi", lambda values: values.sum(min_count=1)), source_row_count=("kpi", "size"))
        .reset_index()
    )
    aggregated["region_raw"] = aggregated["region"]
    aggregated["metric_name"] = aggregated["metric"]
    aggregated["selected_aggregation"] = region_col
    aggregated["source_data_fingerprint"] = fingerprint
    aggregated = aggregated[
        [
            "region",
            "region_raw",
            "date",
            "metric",
            "metric_name",
            "kpi",
            "selected_aggregation",
            "source_data_fingerprint",
            "source_row_count",
        ]
    ].sort_values(["region", "metric", "date"], kind="mergesort")
    aggregated = aggregated.reset_index(drop=True)

    legacy = melted.loc[legacy_mask, ["region", "metric", "date", "kpi"]].copy()
    legacy = legacy.rename(columns={"region": "region_raw", "metric": "metric_name"})
    legacy = legacy.reset_index(drop=True)

    analytical_key_columns = [
        column for column in non_date_cols if column not in {region_col, metric_col}
    ]
    if not analytical_key_columns:
        analytical_key_columns = [region_col]
    analytical_key_columns = [*analytical_key_columns, metric_col]
    duplicate_source_mask = frame.duplicated(subset=analytical_key_columns, keep=False)
    duplicate_analytical_key_rows = int(duplicate_source_mask.sum())
    duplicate_analytical_key_groups = int(
        frame.loc[duplicate_source_mask].drop_duplicates(subset=analytical_key_columns).shape[0]
    )

    duplicate_key_columns = ["region", "metric", "date"]
    duplicate_key_mask = canonical_source.duplicated(subset=duplicate_key_columns, keep=False)
    duplicate_key_rows = int(duplicate_key_mask.sum())
    duplicate_key_groups = int(
        canonical_source.loc[duplicate_key_mask]
        .drop_duplicates(subset=duplicate_key_columns)
        .shape[0]
    )
    retained_dates = melted.loc[legacy_mask, "date"].dropna().sort_values()
    date_range = (retained_dates.iloc[0], retained_dates.iloc[-1]) if len(retained_dates) else None
    inferred_frequency = infer_frequency(retained_dates)
    expected_date_count, missing_dates = expected_and_missing_dates(
        retained_dates, inferred_frequency
    )
    warnings: list[str] = []
    if blank_region_rows:
        warnings.append(f"{blank_region_rows} row(s) had a blank region and were dropped.")
    # Multiple raw keys contributing to one region/date is the intended
    # aggregated layout, not itself a duplicate source key. Surface the
    # warning when the raw analytical key is actually duplicated; retain the
    # regional duplicate counts for diagnostics and legacy compatibility.
    if duplicate_key_rows and duplicate_analytical_key_rows:
        warnings.append(
            f"{duplicate_key_rows} row(s) share a duplicate (region, metric, date) key."
        )
    if duplicate_analytical_key_rows:
        warnings.append(
            f"{duplicate_analytical_key_rows} row(s) share a duplicate analytical key "
            f"({', '.join(map(str, analytical_key_columns))})."
        )

    quality = DataQualityReport(
        source_rows_read=len(df_raw),
        source_rows_dropped_blank_region=blank_region_rows,
        source_rows_removed=blank_region_rows,
        source_date_columns=len(date_cols),
        observations_expected=len(frame) * len(date_cols),
        observations_retained=len(legacy),
        observations_dropped_missing_kpi=int(missing_kpi_mask.sum()),
        observations_dropped_non_numeric_kpi=int(non_numeric_mask.sum()),
        observations_dropped_invalid_date=int(invalid_date_mask.sum()),
        observations_removed=(len(frame) * len(date_cols)) - len(legacy),
        duplicate_key_rows=duplicate_key_rows,
        duplicate_key_groups=duplicate_key_groups,
        selected_layout=layout,
        selected_aggregation_column=(region_col if layout == "aggregated" else None),
        selected_metric_column=metric_col,
        metrics_found=tuple(sorted(source_observations["metric"].unique().tolist())),
        date_range=date_range,
        inferred_frequency=inferred_frequency,
        expected_date_count=expected_date_count,
        missing_dates=missing_dates,
        raw_regions=raw_regions,
        warnings=tuple(warnings),
        blocking_errors=(),
        source_data_fingerprint=fingerprint,
        canonical_observations=len(aggregated),
        duplicate_analytical_key_rows=duplicate_analytical_key_rows,
        duplicate_analytical_key_groups=duplicate_analytical_key_groups,
    )

    provenance = frame[non_date_cols + [_SOURCE_ROW_COLUMN]].copy()
    provenance["region"] = provenance[region_col].map(_clean_label)
    provenance["metric"] = provenance[metric_col].map(_clean_label)
    provenance["selected_aggregation"] = region_col
    provenance["source_data_fingerprint"] = fingerprint
    if config.metric_value is not None:
        provenance = provenance[provenance["metric"] == str(config.metric_value)].copy()

    return RegionalKPIDataset(
        data=aggregated,
        config=replace(
            config,
            aggregation_column=region_col,
            metric_column=metric_col,
        ),
        quality=quality,
        source_data_fingerprint=fingerprint,
        provenance=provenance.reset_index(drop=True),
        source_observations=source_observations.reset_index(drop=True),
        legacy_data=legacy,
        rejected_rows=rejected_rows,
    )
