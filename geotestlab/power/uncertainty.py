"""Uncertainty around estimated power (Clopper-Pearson binomial interval).

Power is an estimated detection rate k/n over n simulations; the Clopper-Pearson
exact interval is reported alongside every power estimate so the decision
record includes uncertainty around power.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import beta


def clopper_pearson(k: int, n: int, alpha: float) -> tuple:
    """Exact Clopper-Pearson ``(1 - alpha)`` CI for a binomial proportion k/n."""
    if n <= 0:
        return (np.nan, np.nan)
    if k == 0:
        lower = 0.0
    else:
        lower = float(beta.ppf(alpha / 2, k, n - k + 1))
    if k == n:
        upper = 1.0
    else:
        upper = float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return (lower, upper)


def power_with_ci(detected: np.ndarray, alpha: float) -> tuple:
    """Return (power, ci_lower, ci_upper) for a boolean detection array."""
    n = int(len(detected))
    k = int(np.sum(detected))
    power = (k / n) if n else np.nan
    lower, upper = clopper_pearson(k, n, alpha)
    return float(power), lower, upper
