"""Error metrics and residual diagnostics for time-series validation.

Pure (no Streamlit).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import mean_squared_error, r2_score


def _is_valid_number(v):
    """Shared validity check used by the ``classify_*`` traffic-light helpers.

    Returns False for None, NaN, pd.NA, and +/-inf; True for any other finite
    number.
    """
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        return False
    try:
        if not np.isfinite(float(v)):
            return False
    except (TypeError, ValueError):
        return False
    return True


def smape(actual, pred):
    """Symmetric mean absolute percentage error (%)."""
    denom = (np.abs(actual) + np.abs(pred)) / 2
    denom = np.where(denom == 0, 1e-8, denom)
    return np.mean(np.abs(actual - pred) / denom) * 100


def compute_metrics(actual, pred):
    """Return ``(corr, r2, smape, rmse)`` for the actual vs predicted series."""
    corr = np.corrcoef(actual, pred)[0, 1]
    r2 = r2_score(actual, pred)
    s = smape(actual, pred)
    rmse = np.sqrt(mean_squared_error(actual, pred))
    return corr, r2, s, rmse


def durbin_watson_stat(residuals):
    """Durbin-Watson statistic for residual autocorrelation.

    ~2.0 = little autocorrelation; <2 suggests positive autocorrelation; >2
    suggests negative autocorrelation. Implemented manually (no statsmodels
    dependency). Returns NaN when fewer than 3 finite residuals or zero variance.
    """
    residuals = np.asarray(residuals, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) < 3:
        return np.nan
    denom = np.sum(residuals**2)
    if denom == 0:
        return np.nan
    return np.sum(np.diff(residuals) ** 2) / denom
