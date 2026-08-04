"""Minimum Detectable Effect search (PA-FR6) for the power spike.

The MDE is the smallest effect within the documented bounds whose estimated
power reaches the target power, refined to the search tolerance. Bounds and
tolerance are recorded in the result; a failure to find an MDE is explicit.
"""

from __future__ import annotations

import numpy as np


def find_mde(power_at, bounds, target, tolerance, n_grid=200):
    """Find the smallest effect meeting ``target`` power within ``bounds``.

    ``power_at(effect) -> float`` is the estimated power for an effect.
    Returns ``(mde, reached, grid, powers)``; ``reached`` is False when no grid
    effect reaches the target.
    """
    lo, hi = float(bounds[0]), float(bounds[1])
    if hi <= lo:
        return None, False, np.array([lo]), np.array([np.nan])
    grid = np.linspace(lo, hi, n_grid)
    powers = np.array([float(power_at(float(e))) for e in grid])
    above = powers >= target
    idx = int(np.argmax(above)) if above.any() else -1
    if idx < 0:
        return None, False, grid, powers
    # Refine with bisection between the last below-target point and the first hit.
    a = grid[idx - 1] if idx > 0 else lo
    b = grid[idx]
    while (b - a) > tolerance and (b - a) > 1e-12:
        m = (a + b) / 2.0
        if float(power_at(float(m))) >= target:
            b = m
        else:
            a = m
    return float(b), True, grid, powers
