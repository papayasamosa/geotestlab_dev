"""Rolling-origin validation and non-contiguous window handling.

Pure (no Streamlit). The Streamlit app wraps ``rolling_origin_validation`` in
``st.cache_data`` for performance; the package function itself is cache-free.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler

from geotestlab.validation.frequency import dates_are_contiguous
from geotestlab.validation.metrics import smape
from geotestlab.validation.regularisation import build_regularized_model


def rolling_origin_validation(
    X,
    y,
    frequency_config,
    horizon=4,
    min_training_periods=13,
    dates=None,
    n_splits=5,
    model_type="enet",
    min_training_weeks=None,
):
    """Expanding-window rolling origin validation.

    Trains on rows ``0:start_idx``, tests on rows ``start_idx:start_idx+horizon``.
    Uses TimeSeriesSplit-based CV to tune regularisation whenever a fold's training
    window has enough periods; folds with too little history fit an exploratory
    fixed-alpha model and are excluded from ``rolling_smape_mean`` /
    ``rolling_rmse_mean``. A held-out window is skipped when its dates are not
    calendar-contiguous at the given frequency.

    Returns ``(fold_df, rolling_smape_mean, rolling_rmse_mean, cv_status,
    windows_skipped_non_contiguous)``. ``n_splits`` is accepted for backwards
    compatibility (ignored) and ``min_training_weeks`` aliases
    ``min_training_periods``.
    """
    if min_training_weeks is not None:
        min_training_periods = min_training_weeks
    n = len(y)
    empty_df = pd.DataFrame(
        columns=[
            "fold_number",
            "training_periods",
            "forecast_horizon_periods",
            "training_weeks",
            "forecast_horizon_weeks",
            "smape",
            "rmse",
            "bias",
            "bias_pct",
            "uplift_error",
            "uplift_error_pct",
            "train_start_date",
            "train_end_date",
            "test_start_date",
            "test_end_date",
            "used_cv_fallback",
        ]
    )
    if n < min_training_periods + horizon:
        return (
            empty_df,
            np.nan,
            np.nan,
            "No folds: insufficient pre-period history for rolling-origin validation.",
            0,
        )

    _dates_valid = dates is not None and len(dates) == n
    folds = []
    fold_num = 0
    windows_skipped_non_contiguous = 0
    _all_starts = list(range(min_training_periods, n - horizon + 1))
    if len(_all_starts) > 20:
        _step = len(_all_starts) // 20
        _all_starts = _all_starts[::_step][:20]
    for start_idx in _all_starts:
        if _dates_valid and not dates_are_contiguous(
            dates[start_idx : start_idx + horizon], frequency_config
        ):
            windows_skipped_non_contiguous += 1
            continue

        train_X, train_y = X[:start_idx], y[:start_idx]
        test_X, test_y = X[start_idx : start_idx + horizon], y[start_idx : start_idx + horizon]
        if len(test_y) < horizon:
            continue

        scaler = StandardScaler()
        train_X_scaled = scaler.fit_transform(train_X)
        test_X_scaled = scaler.transform(test_X)

        if model_type not in ("enet", "lasso"):
            return (
                empty_df,
                np.nan,
                np.nan,
                "Unsupported model_type",
                windows_skipped_non_contiguous,
            )

        model, fold_cv_status, fold_used_cv = build_regularized_model(
            model_type, len(train_y), n_splits_pref=3
        )
        used_cv_fallback = not fold_used_cv

        model.fit(train_X_scaled, train_y)
        pred = model.predict(test_X_scaled)

        fold_smape = smape(test_y, pred)
        fold_rmse = np.sqrt(mean_squared_error(test_y, pred))
        bias = float(np.mean(pred - test_y))
        mean_actual = float(np.mean(test_y))
        bias_pct = bias / mean_actual * 100 if mean_actual != 0 else np.nan
        uplift_error = float(test_y.sum() - pred.sum())
        pred_sum = float(pred.sum())
        uplift_error_pct = uplift_error / pred_sum * 100 if pred_sum != 0 else np.nan

        if dates is not None and len(dates) == n:
            train_start_date = dates[0]
            train_end_date = dates[start_idx - 1]
            test_start_date = dates[start_idx]
            test_end_date = dates[min(start_idx + horizon - 1, n - 1)]
        else:
            train_start_date = train_end_date = test_start_date = test_end_date = None

        fold_num += 1
        folds.append(
            {
                "fold_number": fold_num,
                "training_periods": start_idx,
                "forecast_horizon_periods": horizon,
                "training_weeks": start_idx,
                "forecast_horizon_weeks": horizon,
                "smape": fold_smape,
                "rmse": fold_rmse,
                "bias": bias,
                "bias_pct": bias_pct,
                "uplift_error": uplift_error,
                "uplift_error_pct": uplift_error_pct,
                "train_start_date": train_start_date,
                "train_end_date": train_end_date,
                "test_start_date": test_start_date,
                "test_end_date": test_end_date,
                "used_cv_fallback": used_cv_fallback,
            }
        )

    if not folds:
        return (
            empty_df,
            np.nan,
            np.nan,
            "No folds: insufficient pre-period history for rolling-origin validation.",
            windows_skipped_non_contiguous,
        )

    fold_df = pd.DataFrame(folds)
    n_fallback_folds = int(fold_df["used_cv_fallback"].sum())
    n_cv_folds = len(fold_df) - n_fallback_folds

    cv_fold_df = fold_df[~fold_df["used_cv_fallback"]]
    if n_cv_folds > 0:
        rolling_smape_mean = float(cv_fold_df["smape"].mean())
        rolling_rmse_mean = float(cv_fold_df["rmse"].mean())
    else:
        rolling_smape_mean = np.nan
        rolling_rmse_mean = np.nan

    if n_fallback_folds == 0:
        cv_status = (
            "TimeSeriesSplit cross-validation used to select regularisation strength in all folds."
        )
    elif n_cv_folds == 0:
        cv_status = (
            "Insufficient history for TimeSeriesSplit in all folds; only exploratory fixed-alpha "
            "fits were available, so rolling-origin validation metrics are Insufficient data "
            "rather than being based on a non-cross-validated fallback."
        )
    else:
        cv_status = (
            f"Insufficient history for TimeSeriesSplit in {n_fallback_folds} of {len(fold_df)} folds; "
            f"those folds were exploratory fixed-alpha fits and are excluded from rolling-origin "
            f"validation metrics (based on the remaining {n_cv_folds} TimeSeriesSplit-CV fold(s))."
        )
    return fold_df, rolling_smape_mean, rolling_rmse_mean, cv_status, windows_skipped_non_contiguous


def summarize_rolling_origin_folds(fold_df):
    """Additional rolling-origin summary stats (P90 sMAPE, mean bias, uplift-error
    interval) computed only from TimeSeriesSplit-CV folds — exploratory fixed-alpha
    fallback folds are excluded. Returns a dict; all np.nan if no CV folds exist.
    """
    if not fold_df.empty:
        cv_fold_df = fold_df[~fold_df["used_cv_fallback"]]
    else:
        cv_fold_df = fold_df

    if cv_fold_df.empty:
        return {
            "rolling_smape_p90": np.nan,
            "rolling_bias_pct_mean": np.nan,
            "rolling_uplift_error_pct_median": np.nan,
            "rolling_uplift_error_pct_lower": np.nan,
            "rolling_uplift_error_pct_upper": np.nan,
        }

    valid_uplift_errs = cv_fold_df["uplift_error_pct"].dropna()
    if len(valid_uplift_errs) >= 2:
        lower, upper = np.percentile(valid_uplift_errs, [2.5, 97.5])
        lower, upper = float(lower), float(upper)
    else:
        lower = upper = np.nan

    return {
        "rolling_smape_p90": float(np.percentile(cv_fold_df["smape"], 90)),
        "rolling_bias_pct_mean": float(cv_fold_df["bias_pct"].mean()),
        "rolling_uplift_error_pct_median": float(np.median(valid_uplift_errs))
        if len(valid_uplift_errs)
        else np.nan,
        "rolling_uplift_error_pct_lower": lower,
        "rolling_uplift_error_pct_upper": upper,
    }
