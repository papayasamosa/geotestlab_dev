"""Frequency configuration and inference for time-series validation.

Pure (no Streamlit). ``get_frequency_config`` returns a typed
:class:`~geotestlab.validation.models.FrequencyConfig` that also supports
dict-style access so existing callers keep working unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.validation.models import FrequencyConfig


def get_frequency_config(time_series_frequency: str) -> FrequencyConfig:
    """Return frequency-aware validation settings.

    ``time_series_frequency`` is "weekly" or "daily"; anything else falls back
    to "weekly" (preserving existing behaviour).
    """
    if time_series_frequency == "daily":
        return FrequencyConfig(
            frequency="daily",
            period_label_singular="day",
            period_label_plural="days",
            lag_periods=7,
            lag_label="7-day",
            default_min_training_periods=84,
            default_validation_horizon_periods=28,
            default_placebo_length_periods=28,
        )
    # Default / fallback: weekly (preserves existing behaviour)
    return FrequencyConfig(
        frequency="weekly",
        period_label_singular="week",
        period_label_plural="weeks",
        lag_periods=1,
        lag_label="1-week",
        default_min_training_periods=13,
        default_validation_horizon_periods=4,
        default_placebo_length_periods=4,
    )


def infer_time_series_frequency(dates):
    """Infer whether dates look daily or weekly, based on the median gap.

    Suggestion/warning helper only — never use it to silently override a user's
    explicit selection. Returns "daily" / "weekly" / "unknown".
    """
    try:
        unique_dates = sorted(pd.to_datetime(pd.Series(list(dates))).dropna().unique())
    except Exception:
        return "unknown"
    if len(unique_dates) < 2:
        return "unknown"
    diffs = np.diff(np.array(unique_dates)).astype("timedelta64[D]").astype(int)
    if len(diffs) == 0:
        return "unknown"
    median_diff = float(np.median(diffs))
    if 0.5 <= median_diff <= 1.5:
        return "daily"
    elif 5.5 <= median_diff <= 8.5:
        return "weekly"
    else:
        return "unknown"


def dates_are_contiguous(dates, frequency_config) -> bool:
    """True if consecutive dates are each exactly one period apart (7 calendar days
    for weekly, 1 day for daily) with no gap. Used to keep rolling-origin/placebo
    evaluation windows from silently spanning an excluded or missing date as though
    the series were unbroken."""
    period_days = 1 if frequency_config.get("frequency") == "daily" else 7
    step = pd.Timedelta(days=period_days)
    ts = pd.to_datetime(pd.Series(list(dates)))
    if len(ts) < 2:
        return True
    return bool((ts.diff().dropna() == step).all())
