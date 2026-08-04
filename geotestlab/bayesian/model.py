"""PyMC model construction, sampling, and posterior extraction.

PyMC is imported lazily inside these functions (never at module import) to
preserve the app's startup behaviour on Python 3.14 and avoid segfaults/Numba
errors. Model construction and posterior extraction are deterministic and fast;
sampling is the only heavy step and is kept out of the fast test path.
"""

from __future__ import annotations

import numpy as np

from geotestlab.bayesian.models import PosteriorDraws


def build_bayesian_model(X_pre_scaled, y_pre_scaled, prior_sigmas, use_ar1_errors):
    """Build the Bayesian TBR model (intercept + control coefficients).

    When AR(1) errors are enabled, sigma is the *innovation* SD (per-period
    shock); the marginal residual SD is sigma / sqrt(1 - rho^2). When disabled,
    sigma is the plain i.i.d. residual SD, as before.
    """
    import pymc as pm

    with pm.Model() as bmodel:
        intercept = pm.Normal("intercept", mu=0, sigma=1)
        coeffs = pm.Normal(
            "coeffs",
            mu=0,
            sigma=prior_sigmas,
            shape=X_pre_scaled.shape[1],
        )
        sigma = pm.HalfNormal("sigma", sigma=1)
        mu = intercept + pm.math.dot(X_pre_scaled, coeffs)
        if use_ar1_errors:
            # AR(1) residuals: e_t = rho * e_{t-1} + nu_t, nu_t ~ N(0, sigma).
            # Exact likelihood via the conditional (Cochrane-Orcutt style)
            # factorisation: the first observation uses the stationary
            # marginal N(mu_0, sigma / sqrt(1 - rho^2)); every later
            # observation is N(mu_t + rho * (y_{t-1} - mu_{t-1}), sigma).
            # This makes the model - and every interval derived from it - aware
            # of period-to-period autocorrelation instead of assuming
            # independent noise (see Durbin-Watson in the validation tabs).
            rho = pm.Uniform("rho", lower=-0.99, upper=0.99)
            pm.Normal(
                "y_obs_first",
                mu=mu[0],
                sigma=sigma / pm.math.sqrt(1.0 - rho**2),
                observed=y_pre_scaled[0],
            )
            pm.Normal(
                "y_obs",
                mu=mu[1:] + rho * (y_pre_scaled[:-1] - mu[:-1]),
                sigma=sigma,
                observed=y_pre_scaled[1:],
            )
        else:
            pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y_pre_scaled)
    return bmodel


def sample_bayesian_model(
    bmodel,
    draws=2000,
    tune=1000,
    chains=4,
    target_accept=0.95,
    random_seed=42,
):
    """Sample the model with the production profile (seeded, no progress bar)."""
    import pymc as pm

    with bmodel:
        trace = pm.sample(
            draws=draws,
            tune=tune,
            chains=chains,
            target_accept=target_accept,
            progressbar=False,
            random_seed=random_seed,
        )
    return trace


def count_divergences(trace) -> int:
    """Total divergent transitions across all chains (0-safe)."""
    return int(np.asarray(trace.sample_stats["diverging"].values).sum())


def extract_posterior(trace, n_features, use_ar1_errors) -> PosteriorDraws:
    """Flatten posterior arrays from a trace into :class:`PosteriorDraws`.

    rho posterior draws are zeros when AR(1) is off, so all downstream
    predictive code is a single path that degrades gracefully.
    """
    post_int = trace.posterior["intercept"].values.flatten()
    post_coeff = trace.posterior["coeffs"].values.reshape(-1, n_features)
    post_sigma = trace.posterior["sigma"].values.flatten()
    post_rho = (
        trace.posterior["rho"].values.flatten() if use_ar1_errors else np.zeros_like(post_sigma)
    )
    return PosteriorDraws(
        post_int=post_int,
        post_coeff=post_coeff,
        post_sigma=post_sigma,
        post_rho=post_rho,
    )
