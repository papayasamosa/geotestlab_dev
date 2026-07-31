"""Typed results for the KPI ingestion and region-mapping seams."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Schema versions so callers can detect and handle report-shape changes.
DATA_QUALITY_REPORT_SCHEMA_VERSION = 2
REGION_MAPPING_REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DataQualityReport:
    """Parse-level data-quality metadata with explicit, unambiguous units.

    ``source_*`` fields count rows in the raw workbook sheet; ``observation_*``
    fields count long-format (region, metric, date) rows after melting.
    """

    # --- Source (workbook) level ---
    source_rows_read: int
    source_rows_dropped_blank_region: int
    source_rows_removed: int
    source_date_columns: int

    # --- Long-format observation level ---
    observations_expected: int
    observations_retained: int
    observations_dropped_missing_kpi: int
    observations_dropped_non_numeric_kpi: int
    observations_dropped_invalid_date: int
    observations_removed: int

    # --- Duplicates ---
    duplicate_key_rows: int
    duplicate_key_groups: int

    # --- Layout / selection ---
    selected_layout: str
    selected_aggregation_column: str | None
    selected_metric_column: str | None
    metrics_found: tuple[str, ...]

    # --- Date coverage ---
    date_range: tuple[pd.Timestamp, pd.Timestamp] | None
    inferred_frequency: str
    expected_date_count: int
    missing_dates: tuple[pd.Timestamp, ...]

    # --- Regions ---
    raw_regions: tuple[str, ...]

    # --- Messages ---
    warnings: tuple[str, ...]
    blocking_errors: tuple[str, ...]

    # --- Schema ---
    schema_version: int = DATA_QUALITY_REPORT_SCHEMA_VERSION


@dataclass(frozen=True)
class RegionMappingReport:
    """Mapping-level quality: raw region labels vs canonical mapped regions.

    ``unmapped_rows`` holds the long-format rows whose region could not be
    mapped (None when everything mapped), for download/export.
    """

    raw_regions: tuple[str, ...]
    mapped_regions: tuple[str, ...]
    unmapped_regions: tuple[str, ...]
    unmapped_rows: pd.DataFrame | None

    schema_version: int = REGION_MAPPING_REPORT_SCHEMA_VERSION


@dataclass(frozen=True)
class ParsedKPIData:
    """Typed result of KPI ingestion: long-format data + quality metadata.

    ``rejected_rows`` holds the long-format observations dropped during
    parsing (missing/non-numeric KPI, invalid date), for download; None when
    nothing was rejected.
    """

    data: pd.DataFrame
    quality: DataQualityReport
    rejected_rows: pd.DataFrame | None = None


def compute_mapping_report(mapped_frame: pd.DataFrame) -> RegionMappingReport:
    """Build a RegionMappingReport from a frame with ``region_raw`` and ``region`` columns.

    ``region`` holds the resolved canonical region (NaN/blank for unmapped
    rows).  Pure function — no Streamlit dependency.
    """
    if "region_raw" not in mapped_frame.columns or "region" not in mapped_frame.columns:
        raise ValueError("mapped_frame must contain 'region_raw' and 'region' columns")

    def _norm(value) -> str:
        return str(value).strip() if value is not None and pd.notna(value) else ""

    clean_raw = mapped_frame["region_raw"].map(_norm)
    raw_regions = tuple(sorted(clean_raw[clean_raw != ""].unique().tolist()))

    unmapped_mask = mapped_frame["region"].isna() | (
        mapped_frame["region"].astype(str).str.strip() == ""
    )
    unmapped_raw = tuple(
        sorted(clean_raw[unmapped_mask][clean_raw[unmapped_mask] != ""].unique().tolist())
    )
    mapped_raw = tuple(r for r in raw_regions if r not in set(unmapped_raw))
    unmapped_rows = mapped_frame.loc[unmapped_mask].copy() if bool(unmapped_mask.any()) else None

    return RegionMappingReport(
        raw_regions=raw_regions,
        mapped_regions=mapped_raw,
        unmapped_regions=unmapped_raw,
        unmapped_rows=unmapped_rows,
    )
