"""Time-series-safe regularised model selection.

Pure (no Streamlit). Uses ``TimeSeriesSplit``-based ``ElasticNetCV`` whenever
there is enough pre-period history; never falls back to regular K-fold CV
(leakage) and never treats a fixed-alpha exploratory fit as equivalent to
cross-validated model selection.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import ElasticNet, ElasticNetCV
from sklearn.model_selection import TimeSeriesSplit


def safe_tscv(n_splits, n_periods):
    """Return TimeSeriesSplit only if enough periods (weeks or days), else None."""
    if n_periods < 6:
        return None
    n = min(n_splits, n_periods // 3)
    return TimeSeriesSplit(n_splits=max(2, n))


def build_regularized_model(method_name, n_periods, n_splits_pref=5, fixed_alpha=1.0):
    """Build an ElasticNet-family model for ``method_name`` ("enet" or "lasso").

    Uses TimeSeriesSplit-based ElasticNetCV whenever there are enough pre-period
    observations for safe, leakage-free time-series cross-validation. Otherwise
    returns a fixed-alpha ElasticNet explicitly labelled as exploratory — callers
    must exclude exploratory-fallback results from Counterfactual Confidence and
    from rolling-origin validation metrics used for method comparison.

    Returns ``(model, cv_status, used_cv)`` where ``cv_status`` is a short
    human-readable string and ``used_cv`` is True only when TimeSeriesSplit-based
    ElasticNetCV was used.
    """
    tscv = safe_tscv(n_splits_pref, n_periods)
    if tscv is not None:
        if method_name == "enet":
            model = ElasticNetCV(
                l1_ratio=[0.1, 0.3, 0.5, 0.7, 0.9, 0.95],
                alphas=np.logspace(-4, 4, 50),
                cv=tscv,
                max_iter=10000,
                random_state=42,
            )
        else:  # lasso
            model = ElasticNetCV(
                l1_ratio=1, alphas=np.logspace(-4, 4, 100), cv=tscv, max_iter=10000, random_state=42
            )
        return (
            model,
            "TimeSeriesSplit cross-validation used to select regularisation strength.",
            True,
        )
    l1_ratio = 1.0 if method_name == "lasso" else 0.5
    model = ElasticNet(alpha=fixed_alpha, l1_ratio=l1_ratio, max_iter=10000, random_state=42)
    cv_status = (
        f"Insufficient history for TimeSeriesSplit; exploratory fixed-alpha ElasticNet "
        f"fit (alpha={fixed_alpha}, l1_ratio={l1_ratio}) used instead — NOT cross-validated "
        f"and excluded from Counterfactual Confidence."
    )
    return model, cv_status, False


def classify_validation_method(fold_df, main_model_used_cv_fallback):
    """Short, stakeholder-facing summary of whether rolling-origin validation used
    leakage-free TimeSeriesSplit cross-validation, only partially did so, or wasn't
    possible at all due to insufficient pre-period history.

    - 🟢 "Rolling-origin validation": every fold used TimeSeriesSplit CV.
    - 🟡 "Partial rolling-origin validation": some folds were excluded (exploratory
      fixed-alpha fallback, excluded from headline metrics).
    - ⚪ "Insufficient validation history": no valid TimeSeriesSplit-CV fold.
    """
    if (
        main_model_used_cv_fallback
        or fold_df is None
        or fold_df.empty
        or "used_cv_fallback" not in fold_df.columns
    ):
        return "⚪ Insufficient validation history"
    n_fallback_folds = int(fold_df["used_cv_fallback"].sum())
    if n_fallback_folds == 0:
        return "🟢 Rolling-origin validation"
    elif n_fallback_folds < len(fold_df):
        return "🟡 Partial rolling-origin validation"
    else:
        return "⚪ Insufficient validation history"
