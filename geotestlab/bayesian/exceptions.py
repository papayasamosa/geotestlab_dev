"""Domain exceptions for the Bayesian core.

The service is return-based (it always returns a typed :class:`BayesianResult`);
these exceptions are raised by the lower-level builders so the service can
translate them into structured ``errors`` on a non-completed result.
"""


class BayesianError(Exception):
    """Base class for Bayesian-core errors."""


class InsufficientPrePeriodError(BayesianError):
    """Not enough pre-period rows to build the Bayesian model."""


class MissingTestPeriodError(BayesianError):
    """No test-period rows available in the combined model matrix."""
