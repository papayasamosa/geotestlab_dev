"""Excel ingestion adapter for the canonical regional KPI contract.

This module keeps the historical ``load_and_reshape_kpi`` entry point and its
legacy long-frame output.  Layout detection, coercion, missingness handling,
aggregation, provenance, and quality diagnostics live in
``geotestlab.data.regional`` so new consumers do not create another parser.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .exceptions import NoRetainedKPIObservationsError, UnreadableWorkbookError
from .models import ParsedKPIData
from .regional import (
    RegionalKPIConfig,
    detect_date_columns,
    detect_metric_column,
    expected_and_missing_dates,
    infer_frequency,
    prepare_regional_kpi,
)


def _expected_and_missing_dates(dates, frequency: str) -> tuple[int, tuple[pd.Timestamp, ...]]:
    """Backwards-compatible private alias for the canonical date helper."""

    return expected_and_missing_dates(dates, frequency)


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
    """Load a workbook and return the legacy view plus its canonical dataset.

    The legacy ``ParsedKPIData.data`` intentionally contains one retained row
    per source row/date, matching the existing validation behaviour.  The
    ``regional_dataset`` field is the reusable, aggregated contract for new
    matching, validation, and test-sizing consumers.
    """

    dataset = prepare_regional_kpi(
        _read_workbook(uploaded_file),
        config=RegionalKPIConfig(aggregation_column=agg_col, metric_column=metric_col),
    )
    if dataset.legacy_data.empty:
        raise NoRetainedKPIObservationsError(
            "No KPI observations remain after removing invalid dates and missing/"
            "non-numeric KPI values."
        )
    quality = dataset.quality
    if quality.duplicate_key_rows and not any(
        "duplicate" in warning for warning in quality.warnings
    ):
        quality = replace(
            quality,
            warnings=(
                *quality.warnings,
                f"{quality.duplicate_key_rows} row(s) share a duplicate (region, metric, date) key.",
            ),
        )
    return ParsedKPIData(
        data=dataset.legacy_data.copy(),
        quality=quality,
        rejected_rows=dataset.rejected_rows,
        regional_dataset=dataset,
    )


__all__ = [
    "_expected_and_missing_dates",
    "detect_date_columns",
    "detect_metric_column",
    "infer_frequency",
    "load_and_reshape_kpi",
]
