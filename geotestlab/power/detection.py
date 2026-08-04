"""Detection criteria for the power spike (PA-FR4 decision evidence).

A "detected effect" is defined by the chosen criterion applied to simulated
test-window totals. The spike supports only criteria that are actually applied,
and a criterion is never recorded unless it was applied:

- ``interval_excludes_zero`` — the observed total under the effect lies beyond
  the null distribution's central ``(1 - alpha)`` band (per side). Implemented
  for every method.
- ``empirical_placebo_threshold`` — the measured placebo uplift exceeds the
  empirical placebo null threshold (the legacy closed-form approach).
  Implemented for the ``placebo_empirical`` method only; rejected for other
  methods.
- ``sign_and_threshold`` — NOT implemented in this spike: it needs a decision
  threshold field and a sign-aware detection rule, so it is rejected.
"""

from __future__ import annotations

import numpy as np

from geotestlab.power.models import DETECTION_CRITERIA


def critical_values(null_totals: np.ndarray, side: str, alpha: float) -> tuple:
    """Critical threshold(s) of the null total distribution for the given side.

    Returns ``(lower, upper)`` where the unused tail is ``-inf`` / ``+inf``.
    """
    null = np.asarray(null_totals, dtype=float)
    if side == "one_sided_positive":
        return (-np.inf, float(np.percentile(null, (1 - alpha) * 100)))
    if side == "one_sided_negative":
        return (float(np.percentile(null, alpha * 100)), np.inf)
    return (
        float(np.percentile(null, (alpha / 2) * 100)),
        float(np.percentile(null, (1 - alpha / 2) * 100)),
    )


def power_from_totals(
    null_totals: np.ndarray,
    alt_totals: np.ndarray,
    side: str,
    alpha: float,
) -> float:
    """Share of alternative simulations detected against the null distribution."""
    lower, upper = critical_values(null_totals, side, alpha)
    alt = np.asarray(alt_totals, dtype=float)
    if side == "one_sided_positive":
        return float(np.mean(alt > upper))
    if side == "one_sided_negative":
        return float(np.mean(alt < lower))
    return float(np.mean((alt < lower) | (alt > upper)))


def validate_detection_criterion(criterion: str, method: str | None = None) -> None:
    if criterion not in DETECTION_CRITERIA:
        raise ValueError(
            f"Unknown detection criterion {criterion!r}; expected one of {DETECTION_CRITERIA}"
        )
    if criterion == "sign_and_threshold":
        raise ValueError(
            "detection criterion 'sign_and_threshold' is not implemented: it "
            "requires a decision-threshold field and a sign-aware detection "
            "rule. Use 'interval_excludes_zero', or 'empirical_placebo_threshold' "
            "with the placebo_empirical method."
        )
    if criterion == "empirical_placebo_threshold" and method != "placebo_empirical":
        raise ValueError(
            "detection criterion 'empirical_placebo_threshold' is implemented "
            f"only for the placebo_empirical method; got method={method!r}"
        )
