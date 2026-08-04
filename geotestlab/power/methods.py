"""Candidate power methods for the Stage 5 spike (PA-FR2 decision evidence).

Three candidate first-release methods are implemented against controlled
synthetic cases. Each returns ``(null, alt_fn, meta)`` where ``null`` is the
no-effect sample distribution (test-window totals, or placebo uplift-%),
``alt_fn(effect, injection)`` returns the alternative sample under an injected
effect, and ``meta`` carries diagnostics (windows used, failures, warnings).

- ``model_simulation`` — model-based counterfactual simulation: fit the test
  region on its controls over the pre-period, fit AR(1) on the residuals, then
  simulate test-window counterfactual totals under the null and under each
  injected effect (aligned with the app's evaluation method);
- ``placebo_empirical`` — empirical placebo-window power: use pre-period
  placebo-window measured uplift-% as the null and apply the legacy closed-form
  shift (the method behind ``compute_power_curve``) — NOT treated as approved
  without explicit review;
- ``residual_simulation`` — historical residual simulation: bootstrap the
  pre-period residuals to build the null total distribution.
"""

from __future__ import annotations

import numpy as np
from numpy.linalg import LinAlgError

from geotestlab.power.synthetic import TEST_REGION


# ---------------------------------------------------------------------------
# Estimation helpers
# ---------------------------------------------------------------------------
def fit_counterfactual(pre_df, control_regions):
    """OLS fit of the test KPI on controls over the pre-period (levels).

    Returns ``(coef, cf_fit_pre, resid)``. Falls back to a constant-mean
    counterfactual if the design matrix is singular (fallback-fit policy).
    """
    test = pre_df[pre_df["region"] == TEST_REGION].sort_values("date")
    cols = []
    for r in control_regions:
        c = pre_df[pre_df["region"] == r].sort_values("date")
        cols.append(c["kpi"].to_numpy())
    X = np.column_stack([np.ones(len(test)), *cols]) if cols else np.ones((len(test), 1))
    y = test["kpi"].to_numpy()
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    except LinAlgError:
        coef = np.zeros(X.shape[1])
        coef[0] = float(np.mean(y))
    cf_fit = X @ coef
    return coef, cf_fit, y - cf_fit


def fit_ar1(residuals):
    """Cochrane-Orcutt-style AR(1) fit on residuals: returns (rho, sigma)."""
    r = np.asarray(residuals, dtype=float)
    if len(r) < 3:
        return 0.0, float(np.std(r)) if len(r) else 0.0
    rho = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if np.std(r[:-1]) > 0 else 0.0
    rho = float(np.clip(rho, -0.99, 0.99))
    innov = r[1:] - rho * r[:-1]
    sigma = float(np.std(innov, ddof=1)) if len(innov) > 1 else float(np.std(innov))
    return rho, sigma


def _simulate_ar1_paths(rho, sigma, n_periods, n_sim, rng, e_start=0.0):
    out = np.empty((n_sim, n_periods))
    prev = np.full(n_sim, e_start, dtype=float)
    for t in range(n_periods):
        prev = rho * prev + rng.normal(0.0, sigma, size=n_sim)
        out[:, t] = prev
    return out


def _project_test_cf(coef, test_df, control_regions):
    test = test_df[test_df["region"] == TEST_REGION].sort_values("date")
    cols = []
    for r in control_regions:
        c = test_df[test_df["region"] == r].sort_values("date")
        cols.append(c["kpi"].to_numpy())
    X = np.column_stack([np.ones(len(test)), *cols]) if cols else np.ones((len(test), 1))
    return X @ coef


def _shift(null, cf_test_sum, effect, injection, n_test):
    """Alternative totals = null totals shifted by the effect mean.

    Absolute effects shift every test period by a constant; relative effects
    scale the counterfactual total by ``effect/100``. Non-positive null totals
    under a relative effect are marked NaN (low-volume guard) and returned as
    failures by the caller.
    """
    if injection == "absolute":
        return null + effect * n_test, 0
    shift = cf_test_sum * (effect / 100.0)
    alt = null + shift
    bad = null <= 0
    alt = np.where(bad, np.nan, alt)
    return alt, int(np.sum(bad))


# ---------------------------------------------------------------------------
# 1. Model-based counterfactual simulation
# ---------------------------------------------------------------------------
def model_simulation(pre_df, test_df, control_regions, n_test, n_sim, rng):
    """Null totals via AR(1) counterfactual paths; alt = null shifted by effect."""
    coef, _, resid = fit_counterfactual(pre_df, control_regions)
    rho, sigma = fit_ar1(resid)
    e_start = float(resid[-1]) if len(resid) else 0.0
    paths = _simulate_ar1_paths(rho, sigma, n_test, n_sim, rng, e_start=e_start)
    cf_fit_test = _project_test_cf(coef, test_df, control_regions)
    cf_test_sum = float(np.sum(cf_fit_test))
    null = cf_test_sum + paths.sum(axis=1)

    def alt_fn(effect, injection):
        return _shift(null, cf_test_sum, effect, injection, n_test)

    meta = {
        "windows_available": int(len(resid)),
        "windows_used": int(len(resid)),
        "rho_estimate": rho,
        "sigma_estimate": sigma,
        "failures": 0,
        "warnings": [],
    }
    return null, alt_fn, meta


# ---------------------------------------------------------------------------
# 2. Placebo-window empirical method
# ---------------------------------------------------------------------------
def build_placebo_windows(pre_df, control_regions, window_len):
    """Non-overlapping placebo windows in the pre-period.

    Returns the measured placebo uplift-% per window (window actual total minus
    fitted counterfactual total, relative to the fitted total).
    """
    test = pre_df[pre_df["region"] == TEST_REGION].sort_values("date").reset_index(drop=True)
    y = test["kpi"].to_numpy()
    _, cf_fit, _ = fit_counterfactual(pre_df, control_regions)
    n = len(y)
    pcts = []
    for start in range(0, n - window_len + 1, window_len):
        denom = float(np.sum(cf_fit[start : start + window_len]))
        if denom != 0 and np.isfinite(denom):
            pcts.append(float((np.sum(y[start : start + window_len]) - denom) / denom * 100.0))
    return np.array(pcts, dtype=float)


def placebo_empirical(pre_df, test_df, control_regions, n_test, n_sim, rng):
    """Placebo uplift-% null; alt = legacy closed-form shift (relative only)."""
    pcts = build_placebo_windows(pre_df, control_regions, n_test)
    if len(pcts) == 0:
        pcts = np.array([0.0])
    null = pcts

    def alt_fn(effect, injection):
        if injection == "absolute":
            raise NotImplementedError(
                "placebo_empirical supports relative injection only (documented limitation)"
            )
        return pcts * (1.0 + effect / 100.0) + effect, 0

    meta = {
        "windows_available": len(pcts),
        "windows_used": len(pcts),
        "failures": 0,
        "warnings": [],
    }
    return null, alt_fn, meta


# ---------------------------------------------------------------------------
# 3. Historical residual simulation (bootstrap)
# ---------------------------------------------------------------------------
def residual_simulation(pre_df, test_df, control_regions, n_test, n_sim, rng):
    """Null totals by resampling pre-period residuals (with replacement)."""
    coef, _, resid = fit_counterfactual(pre_df, control_regions)
    if len(resid) == 0:
        resid = np.array([0.0])
    boots = rng.choice(resid, size=(n_sim, n_test), replace=True)
    cf_fit_test = _project_test_cf(coef, test_df, control_regions)
    cf_test_sum = float(np.sum(cf_fit_test))
    null = cf_test_sum + boots.sum(axis=1)

    def alt_fn(effect, injection):
        return _shift(null, cf_test_sum, effect, injection, n_test)

    meta = {
        "windows_available": int(len(resid)),
        "windows_used": int(len(resid)),
        "failures": 0,
        "warnings": [],
    }
    return null, alt_fn, meta


METHODS = {
    "model_simulation": model_simulation,
    "placebo_empirical": placebo_empirical,
    "residual_simulation": residual_simulation,
}
