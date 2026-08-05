"""Minimum Detectable Effect search (PA-FR6) for the power spike.

The MDE is the smallest effect within the documented bounds whose estimated
power reaches the target power, refined to the search tolerance. Bounds and
tolerance are recorded in the result; a failure to find an MDE is explicit.
"""

from __future__ import annotations

import numpy as np


def validate_mde_config(
    mde_bounds,
    target_power,
    mde_tolerance,
    alpha=None,
    n_simulations=None,
) -> None:
    """Validate the MDE-search configuration before any simulation.

    MDE is a non-negative magnitude, so negative bounds are rejected; the
    upper bound must be strictly above the lower bound; bounds, tolerance,
    target power and alpha must be finite (a non-finite bound would otherwise
    produce a meaningless effect grid); the tolerance must be positive;
    target power and alpha must lie strictly inside ``(0, 1)``; and the
    simulation count, when provided, must be positive.
    """
    lower, upper = float(mde_bounds[0]), float(mde_bounds[1])
    if not (np.isfinite(lower) and np.isfinite(upper)):
        raise ValueError(f"MDE bounds must be finite; got bounds ({lower}, {upper})")
    if lower < 0.0:
        raise ValueError(
            f"MDE lower bound must be >= 0 (MDE is a non-negative magnitude); got {lower}"
        )
    if upper <= lower:
        raise ValueError(f"MDE upper bound must be > lower bound; got bounds ({lower}, {upper})")
    tolerance = float(mde_tolerance)
    if not np.isfinite(tolerance):
        raise ValueError(f"MDE tolerance must be finite; got {mde_tolerance}")
    if tolerance <= 0.0:
        raise ValueError(f"MDE tolerance must be > 0; got {mde_tolerance}")
    target = float(target_power)
    if not np.isfinite(target) or not 0.0 < target < 1.0:
        raise ValueError(f"target_power must be in (0, 1); got {target_power}")
    if alpha is not None:
        a = float(alpha)
        if not np.isfinite(a) or not 0.0 < a < 1.0:
            raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    if n_simulations is not None and int(n_simulations) <= 0:
        raise ValueError(f"n_simulations must be > 0; got {n_simulations}")


def find_mde(power_at, bounds, target, tolerance, n_grid=200):
    """Find the smallest effect meeting ``target`` power within ``bounds``.

    ``power_at(effect) -> float`` is the estimated power for an effect.
    Returns ``(mde, reached, grid, powers)``; ``reached`` is False when no grid
    effect reaches the target. Invalid bounds/target/tolerance are rejected by
    :func:`validate_mde_config` before any power evaluation.
    """
    validate_mde_config(bounds, target, tolerance)
    lo, hi = float(bounds[0]), float(bounds[1])
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
