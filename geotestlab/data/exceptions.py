"""Domain exceptions for KPI ingestion.

Streamlit-facing code (geotestmatch.py) is expected to catch these and
translate them into the app's existing user-facing messages — this module
must not import Streamlit or call st.stop() itself.
"""

from __future__ import annotations


class IngestionError(Exception):
    """Base class for all KPI ingestion domain errors."""


class UnreadableWorkbookError(IngestionError):
    """Neither the calamine nor the openpyxl engine could read the workbook."""


class MissingIdentifierColumnsError(IngestionError):
    """The workbook doesn't have enough non-date columns to resolve a region
    column and a metric column."""


class UnresolvedAggregationColumnError(IngestionError):
    """The workbook has more than one aggregation-level column, and no
    aggregation column was selected."""


class UnresolvedMetricColumnError(IngestionError):
    """The workbook has more than one aggregation-level column, and no
    metric column was selected."""


class NoValidDateColumnsError(IngestionError):
    """No datetime-typed column headers were found in the workbook."""


class NoRetainedKPIObservationsError(IngestionError):
    """Every parsed row was dropped (invalid dates / missing KPI values),
    leaving no usable observations."""
