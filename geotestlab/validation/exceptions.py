"""Domain exceptions for the validation core (no Streamlit dependency).

The built-in service (``geotestlab.validation.service``) returns structured
results rather than raising for the conditions it handles; these exception
types are the domain's error contract for callers that want exception-based
handling of the two conditions that prevent any model from being built.
"""

from __future__ import annotations


class ValidationError(Exception):
    """Base class for validation-core domain errors."""


class InsufficientPrePeriodError(ValidationError):
    """Too few pre-period rows to fit any model."""


class MissingControlColumnsError(ValidationError):
    """Selected control regions have no matching data in the model matrix."""
