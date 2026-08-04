"""Bayesian TBR core — pure, Streamlit-free model construction, sampling,
predictive simulation, uplift aggregation, and diagnostics.

Modules: exceptions, models, ar1, diagnostics, priors, features, predict,
model, service.
"""

from geotestlab.bayesian.ar1 import ar1_gap_steps, simulate_ar1_predictive_residuals
from geotestlab.bayesian.diagnostics import summarize_mcmc_diagnostics
from geotestlab.bayesian.exceptions import (
    BayesianError,
    InsufficientPrePeriodError,
    MissingTestPeriodError,
)
from geotestlab.bayesian.features import build_bayesian_model_data
from geotestlab.bayesian.model import (
    build_bayesian_model,
    count_divergences,
    extract_posterior,
    sample_bayesian_model,
)
from geotestlab.bayesian.models import (
    BayesianConfig,
    BayesianModelData,
    BayesianResult,
    PosteriorDraws,
    PriorSpec,
)
from geotestlab.bayesian.predict import (
    compute_fitted_mean_intervals,
    compute_predictive_interval,
    compute_uplift_aggregation,
)
from geotestlab.bayesian.priors import (
    build_prior_spec,
    calculate_structural_prior_sigmas,
    compute_correlation_sigma_bounds,
)
from geotestlab.bayesian.service import run_bayesian

__all__ = [
    "BayesianConfig",
    "BayesianError",
    "BayesianModelData",
    "BayesianResult",
    "InsufficientPrePeriodError",
    "MissingTestPeriodError",
    "PosteriorDraws",
    "PriorSpec",
    "ar1_gap_steps",
    "build_bayesian_model",
    "build_bayesian_model_data",
    "build_prior_spec",
    "calculate_structural_prior_sigmas",
    "compute_correlation_sigma_bounds",
    "compute_fitted_mean_intervals",
    "compute_predictive_interval",
    "compute_uplift_aggregation",
    "count_divergences",
    "extract_posterior",
    "run_bayesian",
    "sample_bayesian_model",
    "simulate_ar1_predictive_residuals",
    "summarize_mcmc_diagnostics",
]
