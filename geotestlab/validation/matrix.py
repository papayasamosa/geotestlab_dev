"""Model-matrix construction and calendar-exact lagged controls.

Pure (no Streamlit).
"""

from __future__ import annotations

import pandas as pd

from geotestlab.validation.frequency import get_frequency_config
from geotestlab.validation.models import ModelMatrixDiagnostics


def build_model_matrix(agg_df, control_list, test_regions):
    """Build the model matrix (test KPI + one column per control).

    Returns ``(model, matrix_diagnostics)`` where ``matrix_diagnostics`` is a
    :class:`~geotestlab.validation.models.ModelMatrixDiagnostics` reporting how
    many rows were lost to the ``dropna()`` step (e.g. because a selected control
    had missing KPI values for some dates) so callers can warn the user rather
    than silently losing data. Diagnostics are computed after the merge but
    before ``dropna()``.
    """
    test_agg = (
        agg_df[agg_df["region"].isin(test_regions)]
        .groupby("date")["kpi"]
        .sum()
        .reset_index()
        .rename(columns={"kpi": "test_kpi"})
    )
    control_wide = (
        agg_df[agg_df["region"].isin(control_list)]
        .pivot(index="date", columns="region", values="kpi")
        .reset_index()
    )
    merged = (
        test_agg.merge(control_wide, on="date", how="inner")
        .sort_values("date")
        .reset_index(drop=True)
    )

    rows_before_dropna = len(merged)
    control_cols_present = [c for c in control_list if c in merged.columns]
    control_columns_with_missing = [c for c in control_cols_present if merged[c].isna().any()]

    model = merged.dropna().reset_index(drop=True)
    rows_after_dropna = len(model)
    rows_dropped = rows_before_dropna - rows_after_dropna
    pct_rows_dropped = (
        (rows_dropped / rows_before_dropna * 100.0) if rows_before_dropna > 0 else 0.0
    )

    matrix_diagnostics = ModelMatrixDiagnostics(
        rows_before_dropna=rows_before_dropna,
        rows_after_dropna=rows_after_dropna,
        rows_dropped=rows_dropped,
        pct_rows_dropped=pct_rows_dropped,
        control_columns_with_missing=tuple(control_columns_with_missing),
    )
    return model, matrix_diagnostics


def add_lagged_control_features(
    model_df, control_list, lags=(1,), frequency_config=None, time_series_frequency=None
):
    """Add lagged versions of each control KPI column.

    Each control gets a ``{control}_lag{lag}`` feature containing that control's
    KPI value ``lag`` periods earlier. Uses a true *calendar* lag (weekly lag N
    matches each row to the control's value from exactly ``N*7`` calendar days
    earlier, daily lag N from exactly ``N`` calendar days earlier) via a
    date-keyed merge, never a row-position shift. If the exact source date is
    missing or was excluded, the lag value is left missing and the row is dropped
    by the ``dropna`` step, rather than silently borrowing a nearby date's value.

    Returns ``(model_df_lagged, model_feature_cols, lagged_feature_map,
    lag_drop_metadata)``.
    """
    if frequency_config is None:
        frequency_config = get_frequency_config(
            time_series_frequency if time_series_frequency is not None else "weekly"
        )
    period_days = 1 if frequency_config.get("frequency") == "daily" else 7

    model_df_lagged = model_df.sort_values("date").reset_index(drop=True).copy()
    model_df_lagged["date"] = pd.to_datetime(model_df_lagged["date"])
    rows_before_lag_drop = len(model_df_lagged)
    lagged_feature_map = {}
    lag_cols_all = []

    for c in control_list:
        lagged_feature_map[c] = {"current": c}
        for lag in lags:
            lag_col = f"{c}_lag{lag}"
            lookup = model_df_lagged[["date", c]].copy()
            lookup["date"] = lookup["date"] + pd.Timedelta(days=int(lag) * period_days)
            lookup = lookup.rename(columns={c: lag_col})
            model_df_lagged = model_df_lagged.merge(lookup, on="date", how="left")
            lagged_feature_map[c][f"lag{lag}"] = lag_col
            lag_cols_all.append(lag_col)

    model_df_lagged = model_df_lagged.dropna(subset=lag_cols_all).reset_index(drop=True)
    rows_after_lag_drop = len(model_df_lagged)
    rows_dropped_due_to_lag = rows_before_lag_drop - rows_after_lag_drop
    lag_drop_pct = (
        (rows_dropped_due_to_lag / rows_before_lag_drop * 100.0)
        if rows_before_lag_drop > 0
        else 0.0
    )

    model_feature_cols = list(control_list) + lag_cols_all
    lag_drop_metadata = {
        "rows_before_lag_drop": rows_before_lag_drop,
        "rows_after_lag_drop": rows_after_lag_drop,
        "rows_dropped_due_to_lag": rows_dropped_due_to_lag,
        "lag_drop_pct": lag_drop_pct,
    }
    return model_df_lagged, model_feature_cols, lagged_feature_map, lag_drop_metadata
