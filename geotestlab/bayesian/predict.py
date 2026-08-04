"""Fitted-mean intervals, posterior predictive intervals, and uplift aggregation.

All functions are pure and operate on posterior arrays + a fitted y-scaler, so
they can be tested deterministically with synthetic draws (no PyMC sampling).
"""

from __future__ import annotations

import numpy as np

from geotestlab.bayesian.ar1 import simulate_ar1_predictive_residuals


def compute_fitted_mean_intervals(post_int, post_coeff, X_scaled, scaler_y):
    """Posterior fitted-mean samples (no observation noise).

    Returns ``(mu_scaled, mu_original, y_pred_mean, lower_hdi, upper_hdi)``:
    - ``mu_scaled``: (n_draws, n_periods) fitted means in scaled space;
    - ``mu_original``: same, inverse-transformed back to original units;
    - ``y_pred_mean``: posterior mean of the counterfactual per period;
    - ``lower_hdi`` / ``upper_hdi``: 3% / 97% percentiles of the fitted mean
      (the 94% credible interval around the fitted counterfactual mean).
    """
    mu_scaled = post_int[:, None] + np.dot(post_coeff, X_scaled.T)
    mu_original = scaler_y.inverse_transform(mu_scaled.T).T
    y_pred_mean = mu_original.mean(axis=0)
    lower_hdi = np.percentile(mu_original, 3, axis=0)
    upper_hdi = np.percentile(mu_original, 97, axis=0)
    return mu_scaled, mu_original, y_pred_mean, lower_hdi, upper_hdi


def compute_predictive_interval(
    post_rho, post_sigma, mu_samples_scaled, scaler_y, rng, e_start=None, n_gap_steps=1
):
    """Posterior predictive samples (with observation noise) for one period block.

    Simulates AR(1) residual paths per posterior draw (rho = 0 exactly
    reproduces the previous i.i.d. behaviour), adds them to the fitted-mean
    samples, and returns the 3%/97% predictive interval in original units.

    Returns ``(lower_pi, upper_pi, original_samples, resid)`` where ``resid`` is
    the scaled-space residual path matrix (needed to continue paths into the
    post period).
    """
    resid = simulate_ar1_predictive_residuals(
        post_rho,
        post_sigma,
        mu_samples_scaled.shape[1],
        rng,
        e_start=e_start,
        n_gap_steps=n_gap_steps,
    )
    y_pred_samples = mu_samples_scaled + resid
    original = scaler_y.inverse_transform(y_pred_samples.T).T
    lower_pi = np.percentile(original, 3, axis=0)
    upper_pi = np.percentile(original, 97, axis=0)
    return lower_pi, upper_pi, original, resid


def compute_uplift_aggregation(y_test_actual, total_pred_samples, mu_test_original):
    """Uplift aggregation for the test period.

    - ``y_test_actual``: observed test KPI (1-D);
    - ``total_pred_samples``: per-draw totals of the posterior *predictive*
      counterfactual (original units) — the primary readout;
    - ``mu_test_original``: per-draw fitted-mean counterfactual samples
      (original units) — the narrower credible-interval readout.
    """
    total_actual = float(np.sum(y_test_actual))
    uplift_samples = total_actual - total_pred_samples
    uplift_pi_lower = float(np.percentile(uplift_samples, 3))
    uplift_pi_upper = float(np.percentile(uplift_samples, 97))
    prob_pos = float((uplift_samples > 0).mean())
    mean_uplift = float(uplift_samples.mean())
    uplift_pct = (
        (mean_uplift / total_pred_samples.mean()) * 100
        if total_pred_samples.mean() != 0
        else np.nan
    )

    total_pred_mean_samples = mu_test_original.sum(axis=1)
    uplift_mean_samples = total_actual - total_pred_mean_samples
    uplift_hdi_lower = float(np.percentile(uplift_mean_samples, 3))
    uplift_hdi_upper = float(np.percentile(uplift_mean_samples, 97))

    return {
        "uplift_samples": uplift_samples,
        "uplift_pi_lower": uplift_pi_lower,
        "uplift_pi_upper": uplift_pi_upper,
        "uplift_hdi_lower": uplift_hdi_lower,
        "uplift_hdi_upper": uplift_hdi_upper,
        "prob_pos": prob_pos,
        "mean_uplift": mean_uplift,
        "uplift_pct": uplift_pct,
    }
