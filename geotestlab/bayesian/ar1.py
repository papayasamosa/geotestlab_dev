"""AR(1) gap bridging and residual-path simulation (pure, deterministic)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ar1_gap_steps(last_date, next_date, frequency_config):
    """Number of AR(1) steps between two dates for the given frequency (min 1).

    Used to bridge any calendar gap between the pre-period and the test period
    (or the test period and the post period) when carrying residual paths
    forward: gap steps are simulated with noise and discarded, so a long gap
    naturally decays the carried-over residual toward the stationary
    distribution instead of pretending the periods are adjacent.
    """
    try:
        delta_days = (pd.Timestamp(next_date) - pd.Timestamp(last_date)).days
        period_days = 7 if (frequency_config or {}).get("frequency") == "weekly" else 1
        return max(int(round(delta_days / period_days)), 1)
    except Exception:
        return 1


def simulate_ar1_predictive_residuals(
    post_rho, post_sigma, n_periods, rng, e_start=None, n_gap_steps=1
):
    """
    Simulate AR(1) residual paths for posterior predictive counterfactuals.

        e_t = rho * e_{t-1} + nu_t,   nu_t ~ Normal(0, sigma)

    One path per posterior draw, vectorised across draws.

    Why this exists: the app's headline number is the predictive interval on the
    *total* uplift over the test window. Summing i.i.d. per-period noise assumes
    errors cancel across periods; with positively autocorrelated residuals
    (Durbin-Watson < 2) they partially reinforce instead, so the i.i.d. interval
    is too narrow. Simulating the AR(1) recursion per draw gives the total its
    honest width, and exactly reproduces the old i.i.d. behaviour when rho = 0.

    Args:
        post_rho / post_sigma: 1-D arrays of posterior draws (rho may be all
            zeros, in which case this reduces to i.i.d. Normal(0, sigma) noise).
            sigma is the *innovation* SD when rho != 0.
        n_periods: number of forecast periods to return residuals for.
        rng: a seeded np.random.Generator — the caller controls reproducibility.
        e_start: optional 1-D array (one value per draw) of the residual
            immediately before the forecast window (e.g. the last pre-period
            residual, in scaled space). If None, paths start from the stationary
            distribution Normal(0, sigma / sqrt(1 - rho^2)).
        n_gap_steps: number of AR steps between e_start's period and the first
            forecast period (1 = contiguous). See ar1_gap_steps().

    Returns:
        Array of shape (n_draws, n_periods) of residuals in the *scaled* space
        the model was fit in.
    """
    rho = np.asarray(post_rho, dtype=float)
    sigma = np.asarray(post_sigma, dtype=float)
    n_draws = len(sigma)
    if e_start is None:
        denom = np.sqrt(np.clip(1.0 - rho**2, 1e-12, None))
        prev = rng.normal(0.0, 1.0, size=n_draws) * (sigma / denom)
        warmup = 0  # already stationary; no warm-up needed
    else:
        prev = np.asarray(e_start, dtype=float).copy()
        warmup = max(int(n_gap_steps) - 1, 0)
    for _ in range(warmup):
        prev = rho * prev + rng.normal(0.0, 1.0, size=n_draws) * sigma
    out = np.empty((n_draws, int(n_periods)))
    for t in range(int(n_periods)):
        prev = rho * prev + rng.normal(0.0, 1.0, size=n_draws) * sigma
        out[:, t] = prev
    return out
