"""Placebo-window construction and summary statistics.

Pure (no Streamlit).
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import mean_squared_error
from sklearn.preprocessing import StandardScaler

from geotestlab.validation.frequency import dates_are_contiguous
from geotestlab.validation.metrics import smape
from geotestlab.validation.regularisation import build_regularized_model


def run_placebo_windows(
    model_pre,
    model_feature_cols,
    dates_pre,
    min_training_periods,
    placebo_len,
    method_name,
    frequency_config,
    max_windows=40,
):
    """Simulate a fake intervention across all available historical pre-period
    windows ("placebo testing").

    A candidate window is skipped (not just under-filled) when its ``placebo_len``
    test dates aren't calendar-contiguous at the given frequency. Subsamples to at
    most ``max_windows`` evenly-spaced windows when more are available.

    Returns ``(placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses,
    window_diagnostics)`` — the first four are parallel lists, one entry per USED
    window. ``window_diagnostics`` has ``windows_available``, ``windows_used`` and
    ``windows_skipped_non_contiguous``.
    """
    placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses = [], [], [], []
    window_diagnostics = {
        "windows_available": 0,
        "windows_used": 0,
        "windows_skipped_non_contiguous": 0,
    }

    if placebo_len is None or placebo_len <= 0:
        return placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, window_diagnostics

    n_pre = len(dates_pre)
    if n_pre < placebo_len + min_training_periods:
        return placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, window_diagnostics

    all_starts = list(range(min_training_periods, n_pre - placebo_len + 1))
    if len(all_starts) > max_windows:
        step = len(all_starts) // max_windows
        all_starts = all_starts[::step][:max_windows]
    window_diagnostics["windows_available"] = len(all_starts)

    for start_idx in all_starts:
        train_dates = dates_pre[:start_idx]
        test_dates = dates_pre[start_idx : start_idx + placebo_len]
        if not dates_are_contiguous(test_dates, frequency_config):
            window_diagnostics["windows_skipped_non_contiguous"] += 1
            continue
        m_train = model_pre[
            (model_pre["date"] >= train_dates[0]) & (model_pre["date"] <= train_dates[-1])
        ]
        m_test = model_pre[
            (model_pre["date"] >= test_dates[0]) & (model_pre["date"] <= test_dates[-1])
        ]
        if len(m_train) < min_training_periods or m_test.empty:
            continue

        X_tr = m_train[model_feature_cols].values
        y_tr = m_train["test_kpi"].values
        X_te = m_test[model_feature_cols].values
        y_te = m_test["test_kpi"].values
        scaler_p = StandardScaler()
        X_tr_scaled = scaler_p.fit_transform(X_tr)
        model_p, _placebo_cv_status, _placebo_used_cv = build_regularized_model(
            method_name, len(y_tr), n_splits_pref=3
        )
        model_p.fit(X_tr_scaled, y_tr)
        pred_p = model_p.predict(scaler_p.transform(X_te))

        uplift_p = y_te.sum() - pred_p.sum()
        placebos.append(uplift_p)
        pred_sum = pred_p.sum()
        placebo_uplift_pcts.append((uplift_p / pred_sum) * 100 if pred_sum != 0 else np.nan)
        placebo_smapes.append(smape(y_te, pred_p))
        placebo_rmses.append(np.sqrt(mean_squared_error(y_te, pred_p)))
        window_diagnostics["windows_used"] += 1

    return placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, window_diagnostics


def summarize_placebo_results(placebos, placebo_uplift_pcts, placebo_smapes, placebo_rmses, uplift):
    """Summarize raw per-window placebo lists into the metrics shown in the
    "Placebo Testing" and "Observed Uplift vs Placebos" sections: median/95% range
    of placebo uplift, placebo forecast error, and (if an observed uplift is
    available) how extreme that observed uplift is relative to the placebo
    distribution (percentile rank, one/two-sided p-values, z-score).

    Returns a dict; all values are np.nan if there are no placebo windows.
    """
    if not placebos:
        return {
            "median_uplift": np.nan,
            "p2_5": np.nan,
            "p97_5": np.nan,
            "median_placebo_smape": np.nan,
            "p95_placebo_smape": np.nan,
            "median_placebo_rmse": np.nan,
            "p95_placebo_rmse": np.nan,
            "median_placebo_uplift_pct": np.nan,
            "p2_5_pct": np.nan,
            "p97_5_pct": np.nan,
            "percentile_rank": np.nan,
            "p_one_sided": np.nan,
            "p_two_sided": np.nan,
            "z_score": np.nan,
        }

    median_uplift = np.median(placebos)
    p2_5, p97_5 = np.percentile(placebos, [2.5, 97.5])
    median_placebo_smape = np.median(placebo_smapes) if placebo_smapes else np.nan
    p95_placebo_smape = np.percentile(placebo_smapes, 95) if placebo_smapes else np.nan
    median_placebo_rmse = np.median(placebo_rmses) if placebo_rmses else np.nan
    p95_placebo_rmse = np.percentile(placebo_rmses, 95) if placebo_rmses else np.nan
    median_placebo_uplift_pct = np.median(placebo_uplift_pcts) if placebo_uplift_pcts else np.nan
    p2_5_pct, p97_5_pct = (
        np.percentile(placebo_uplift_pcts, [2.5, 97.5]) if placebo_uplift_pcts else (np.nan, np.nan)
    )

    if uplift is not None:
        percentile_rank = np.mean(np.array(placebos) < uplift) * 100
        p_one_sided = np.mean(np.array(placebos) >= uplift)
        mean_placebo = np.mean(placebos)
        p_two_sided = np.mean(
            np.abs(np.array(placebos) - mean_placebo) >= np.abs(uplift - mean_placebo)
        )
        z_score = (uplift - mean_placebo) / (np.std(placebos) + 1e-12)
    else:
        percentile_rank = p_one_sided = p_two_sided = z_score = np.nan

    return {
        "median_uplift": median_uplift,
        "p2_5": p2_5,
        "p97_5": p97_5,
        "median_placebo_smape": median_placebo_smape,
        "p95_placebo_smape": p95_placebo_smape,
        "median_placebo_rmse": median_placebo_rmse,
        "p95_placebo_rmse": p95_placebo_rmse,
        "median_placebo_uplift_pct": median_placebo_uplift_pct,
        "p2_5_pct": p2_5_pct,
        "p97_5_pct": p97_5_pct,
        "percentile_rank": percentile_rank,
        "p_one_sided": p_one_sided,
        "p_two_sided": p_two_sided,
        "z_score": z_score,
    }
