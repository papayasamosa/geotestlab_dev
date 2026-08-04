"""Controlled synthetic cases for the power-analysis methodology spike.

The generator has a KNOWN counterfactual (test = exact linear combination of
controls) and KNOWN AR(1) noise, so the true null distribution of the
test-window total is analytic and the prototype's power estimates can be
validated against it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

TEST_REGION = "T"


@dataclass
class SyntheticCase:
    """A controlled case with known counterfactual, noise, and effect."""

    df: pd.DataFrame  # long frame: date, region, kpi
    cf: np.ndarray  # true test counterfactual per period (pre+test)
    pre_count: int
    truth: dict  # rho, sigma, b0, test_coeffs, control_betas, var_total, ...


def _ar1_series(n, rho, sigma, rng, e_start=0.0):
    e = np.empty(n)
    prev = e_start
    for t in range(n):
        prev = rho * prev + rng.normal(0.0, sigma)
        e[t] = prev
    return e


def generate_synthetic_case(
    n_pre,
    n_test,
    rho,
    sigma,
    control_betas,
    test_coeffs,
    b0=100.0,
    effect_pct=0.0,
    effect_abs=None,
    shape="step",
    seed=0,
    base_controls=None,
    sd_control_noise=1.0,
) -> SyntheticCase:
    """Generate a controlled weekly-style case.

    Controls:  c_j,t = base_j + w_j * signal_t + N(0, sd_control_noise)
    Counterfactual: cf_t = b0 + sum_j b_j * c_j,t   (exact linear combination)
    Noise:      e_t = rho*e_{t-1} + N(0, sigma)     (AR(1) in levels)
    Observed:   pre  y_t = cf_t + e_t
                test y_t = cf_t * (1 + effect_pct/100) + e_t   (relative)
                       or cf_t + effect_abs + e_t              (absolute)
    ``shape='ramp'`` ramps the effect linearly from 0 to full across the test
    window; ``'step'`` applies it fully from the first test period.
    """
    rng = np.random.default_rng(seed)
    n_total = n_pre + n_test
    signal = np.sin(np.linspace(0, 4 * np.pi, n_total)) * 5.0 + np.linspace(0, 0.5, n_total)

    control_regions = sorted(control_betas.keys())
    base_controls = base_controls or {r: 10.0 for r in control_regions}
    controls = {}
    for r in control_regions:
        w = control_betas[r]
        noise = rng.normal(0.0, sd_control_noise, n_total)
        controls[r] = base_controls[r] + w * signal + noise

    cf = np.full(n_total, b0, dtype=float)
    for r in control_regions:
        cf = cf + test_coeffs[r] * controls[r]

    e = _ar1_series(n_total, rho, sigma, rng)
    y = cf.copy() + e
    if effect_abs is not None:
        if shape == "ramp":
            ramp = np.linspace(0, 1, n_test)
            y[n_pre:] = cf[n_pre:] + e[n_pre:] + effect_abs * ramp
        else:
            y[n_pre:] = cf[n_pre:] + e[n_pre:] + effect_abs
    elif effect_pct != 0.0:
        if shape == "ramp":
            ramp = np.linspace(0, 1, n_test)
            y[n_pre:] = cf[n_pre:] * (1 + effect_pct / 100.0 * ramp) + e[n_pre:]
        else:
            y[n_pre:] = cf[n_pre:] * (1 + effect_pct / 100.0) + e[n_pre:]

    dates = pd.date_range("2025-01-06", periods=n_total, freq="7D")
    rows = []
    for t in range(n_total):
        rows.append({"date": dates[t], "region": TEST_REGION, "kpi": float(y[t])})
        for r in control_regions:
            rows.append({"date": dates[t], "region": r, "kpi": float(controls[r][t])})
    df = pd.DataFrame(rows)

    var_single = sigma**2 / (1 - rho**2)
    var_total = var_single * (n_test + 2 * sum((n_test - k) * rho**k for k in range(1, n_test)))
    truth = {
        "rho": rho,
        "sigma": sigma,
        "b0": b0,
        "test_coeffs": dict(test_coeffs),
        "control_betas": dict(control_betas),
        "cf_sum_test": float(np.sum(cf[n_pre:])),
        "var_total": float(var_total),
        "sd_total": float(np.sqrt(var_total)),
    }
    return SyntheticCase(df=df, cf=cf, pre_count=n_pre, truth=truth)


def analytic_total_variance(rho, sigma, n):
    """Var(sum_{t=1..n} e_t) for a Gaussian AR(1): e_t = rho*e_{t-1} + N(0, sigma)."""
    var_single = sigma**2 / (1 - rho**2)
    return var_single * (n + 2 * sum((n - k) * rho**k for k in range(1, n)))


def analytic_power(mean_null, sd_null, effect_total_shift, alpha, side):
    """Power when the alternative total is N(mean_null + shift, sd_null) and the
    null is N(mean_null, sd_null), under the given side. Exact closed form."""
    if side == "one_sided_positive":
        q = stats.norm.ppf(1 - alpha, mean_null, sd_null)
        return float(stats.norm.sf(q, mean_null + effect_total_shift, sd_null))
    if side == "one_sided_negative":
        q = stats.norm.ppf(alpha, mean_null, sd_null)
        return float(stats.norm.cdf(q, mean_null + effect_total_shift, sd_null))
    # two-sided: reject when |total| falls outside the central (1-alpha) band
    lo = stats.norm.ppf(alpha / 2, mean_null, sd_null)
    hi = stats.norm.ppf(1 - alpha / 2, mean_null, sd_null)
    shift = effect_total_shift
    return float(
        stats.norm.cdf(lo, mean_null + shift, sd_null)
        + stats.norm.sf(hi, mean_null + shift, sd_null)
    )
