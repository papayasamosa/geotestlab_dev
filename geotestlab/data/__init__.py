"""Shared typed data contracts and ingestion adapters."""

from .models import DataQualityReport, MarketSizeMeasure, ParsedKPIData, RegionMappingReport
from .regional import (
    RegionalKPIConfig,
    RegionalKPIDataset,
    detect_date_columns,
    detect_metric_column,
    expected_and_missing_dates,
    infer_frequency,
    prepare_regional_kpi,
    regional_kpi_to_validation_frame,
    regional_kpi_to_wide,
    source_data_fingerprint,
)

__all__ = [
    "DataQualityReport",
    "MarketSizeMeasure",
    "ParsedKPIData",
    "RegionMappingReport",
    "RegionalKPIConfig",
    "RegionalKPIDataset",
    "detect_date_columns",
    "detect_metric_column",
    "expected_and_missing_dates",
    "infer_frequency",
    "prepare_regional_kpi",
    "regional_kpi_to_validation_frame",
    "regional_kpi_to_wide",
    "source_data_fingerprint",
]
