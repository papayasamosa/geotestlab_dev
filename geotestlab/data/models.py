"""Typed results for the KPI ingestion seam."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataQualityReport:
    rows_read: int
    rows_retained: int
    parsed_layout: str
    date_count: int
    metric_names: tuple[str, ...]
    raw_regions: tuple[str, ...]
    blank_region_rows: int
    missing_kpi_values: int
    invalid_date_values: int
    duplicate_keys: int
    warnings: tuple[str, ...]
    blocking_errors: tuple[str, ...]


@dataclass(frozen=True)
class ParsedKPIData:
    data: pd.DataFrame
    quality: DataQualityReport
