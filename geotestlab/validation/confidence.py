"""Counterfactual Confidence: traffic-light classifiers and the priority cascade.

Pure (no Streamlit). The reliability thresholds live here as the single source of
truth; the Streamlit app's ``CONFIG["reliability_thresholds"]`` points at
``RELIABILITY_THRESHOLDS``.
"""

from __future__ import annotations

import numpy as np

from geotestlab.validation.metrics import _is_valid_number

# Single source of truth for the traffic-light bands used by the classify_*
# helpers. Durbin-Watson bands are practical interpretation bands, not formal
# critical-value tests.
RELIABILITY_THRESHOLDS = {
    "durbin_watson_low_band": (1.5, 2.5),  # 🟢 Low autocorrelation risk
    "durbin_watson_moderate_low_band": (
        1.2,
        1.5,
    ),  # 🟡 Moderate (positive autocorrelation side)
    "durbin_watson_moderate_high_band": (
        2.5,
        2.8,
    ),  # 🟡 Moderate (negative autocorrelation side)
    "overfitting_gap_pp": {"low_max": 3, "moderate_max": 5},
    "rolling_smape_pct": {"low_max": 10, "moderate_max": 15},
    "rolling_bias_pct": {"low_max": 5, "moderate_max": 10},
}


def classify_autocorrelation_risk(dw_stat):
    """Traffic-light interpretation of the Durbin-Watson statistic ("Autocorrelation
    Risk" row). Practical interpretation bands, not formal critical-value tests."""
    if not _is_valid_number(dw_stat):
        return "⚪ Insufficient data"

    dw = float(dw_stat)
    _t = RELIABILITY_THRESHOLDS
    _low_lo, _low_hi = _t["durbin_watson_low_band"]
    _mod_lo_lo, _mod_lo_hi = _t["durbin_watson_moderate_low_band"]
    _mod_hi_lo, _mod_hi_hi = _t["durbin_watson_moderate_high_band"]

    if _low_lo <= dw <= _low_hi:
        return "🟢 Low"
    elif (_mod_lo_lo <= dw < _mod_lo_hi) or (_mod_hi_lo < dw <= _mod_hi_hi):
        return "🟡 Moderate"
    else:
        return "🔴 High"


def calculate_overfit_gap(pre_smape, rolling_smape):
    """Overfitting Gap: rolling-origin (out-of-sample) sMAPE minus pre-period
    (in-sample) sMAPE. Returns np.nan if either input is missing/not finite."""
    if not _is_valid_number(pre_smape) or not _is_valid_number(rolling_smape):
        return np.nan
    return float(rolling_smape) - float(pre_smape)


def classify_overfitting_risk(overfit_gap_smape):
    """Traffic-light rating for "Overfitting Risk", based ONLY on the Overfitting Gap."""
    if not _is_valid_number(overfit_gap_smape):
        return "⚪ Insufficient data"
    _t = RELIABILITY_THRESHOLDS["overfitting_gap_pp"]
    if overfit_gap_smape <= _t["low_max"]:
        return "🟢 Low"
    if overfit_gap_smape <= _t["moderate_max"]:
        return "🟡 Moderate"
    return "🔴 High"


def classify_rolling_validation_error(rolling_smape_mean):
    """Traffic-light rating for "Rolling Validation Error", based ONLY on the
    absolute out-of-sample sMAPE."""
    if not _is_valid_number(rolling_smape_mean):
        return "⚪ Insufficient data"
    _t = RELIABILITY_THRESHOLDS["rolling_smape_pct"]
    if rolling_smape_mean <= _t["low_max"]:
        return "🟢 Low"
    if rolling_smape_mean <= _t["moderate_max"]:
        return "🟡 Moderate"
    return "🔴 High"


def classify_rolling_bias_risk(rolling_bias_pct):
    """Traffic-light rating for "Rolling Bias Risk", based ONLY on rolling_bias_pct."""
    if not _is_valid_number(rolling_bias_pct):
        return "⚪ Insufficient data"
    _t = RELIABILITY_THRESHOLDS["rolling_bias_pct"]
    if abs(rolling_bias_pct) <= _t["low_max"]:
        return "🟢 Low"
    if abs(rolling_bias_pct) <= _t["moderate_max"]:
        return "🟡 Moderate"
    return "🔴 High"


def combine_reliability_ratings(component_ratings):
    """Derive the overall "Counterfactual Confidence" rating from component
    traffic-light ratings via a PRIORITY-ORDERED CASCADE (Rolling Validation Error
    is the primary gate; Overfitting, Autocorrelation Risk and Rolling Bias are
    secondary checks that can hold confidence back to moderate but never force it
    to low).
    """

    def _sym(key):
        v = component_ratings.get(key)
        return v.split(" ", 1)[0] if v else "⚪"

    validation_error_sym = _sym("rolling validation error")
    secondary_syms = [
        _sym("overfitting gap"),
        _sym("autocorrelation risk"),
        _sym("rolling bias"),
    ]

    if validation_error_sym == "🔴":
        return "🔴 Low confidence"
    if validation_error_sym == "⚪":
        return "⚪ Insufficient data"
    if validation_error_sym == "🟡":
        return "🟡 Moderate confidence"

    available_secondary = [s for s in secondary_syms if s != "⚪"]
    if any(s in ("🔴", "🟡") for s in available_secondary):
        return "🟡 Moderate confidence"
    return "🟢 High confidence"


def get_reliability_drivers(component_ratings):
    """Human-readable explanation of what drove the Counterfactual Confidence
    rating. Lists ALL flagged issues in priority order (rolling validation error,
    overfitting gap, autocorrelation risk, then rolling bias)."""
    overall = combine_reliability_ratings(component_ratings)
    symbols = {k: v.split(" ", 1)[0] for k, v in component_ratings.items() if v}

    if overall == "🟢 High confidence":
        return "Validation checks passed"
    if overall == "⚪ Insufficient data":
        return "Insufficient validation data to assess confidence"

    priority_order = [
        "rolling validation error",
        "overfitting gap",
        "autocorrelation risk",
        "rolling bias",
    ]
    reds = [f"high {k}" for k in priority_order if symbols.get(k) == "🔴"]
    yellows = [f"moderate {k}" for k in priority_order if symbols.get(k) == "🟡"]
    drivers = reds + yellows
    fallback = (
        "validation checks failed" if overall == "🔴 Low confidence" else "elevated validation risk"
    )
    detail = " + ".join(drivers) if drivers else fallback
    return f"{detail[:1].upper()}{detail[1:]}"
