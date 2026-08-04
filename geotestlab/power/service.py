"""Power-analysis spike service (pure; no Streamlit).

Runs one of the candidate methods against a controlled synthetic case and
returns a typed :class:`PowerResult` with every PA-FR5 output: power curve,
power uncertainty (Clopper-Pearson), MDE, simulation count, seed, detection
criterion, windows used, failures, and warnings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.power.detection import (
    critical_values,
    validate_detection_criterion,
)
from geotestlab.power.mde import find_mde
from geotestlab.power.methods import METHODS
from geotestlab.power.models import (
    EFFECT_INJECTIONS,
    EFFECT_SHAPES,
    SIDES,
    PowerConfig,
    PowerResult,
)
from geotestlab.power.synthetic import TEST_REGION
from geotestlab.power.uncertainty import power_with_ci


def _split_case(case_df, pre_count):
    dates = sorted(pd.to_datetime(pd.Series(case_df["date"].unique())))
    pre_dates = set(dates[:pre_count])
    pre_df = case_df[case_df["date"].isin(pre_dates)].copy()
    test_df = case_df[~case_df["date"].isin(pre_dates)].copy()
    return pre_df, test_df, len(dates) - pre_count


def run_power_analysis(case_df, pre_count, config: PowerConfig) -> PowerResult:
    """Run the power spike for one controlled synthetic case."""
    validate_detection_criterion(config.detection_criterion)
    if config.method not in METHODS:
        raise ValueError(f"Unknown method {config.method!r}; expected one of {list(METHODS)}")
    if config.effect_injection not in EFFECT_INJECTIONS:
        raise ValueError(f"Unknown effect injection {config.effect_injection!r}")
    if config.side not in SIDES:
        raise ValueError(f"Unknown side {config.side!r}")
    if config.effect_shape not in EFFECT_SHAPES:
        raise ValueError(f"Unknown effect shape {config.effect_shape!r}")

    warnings = []
    if pre_count < config.min_historical_periods:
        warnings.append(
            f"pre-period has {pre_count} periods (< recommended minimum "
            f"{config.min_historical_periods})"
        )
    if config.n_simulations < config.min_simulations:
        warnings.append(
            f"n_simulations={config.n_simulations} (< recommended minimum "
            f"{config.min_simulations}); power estimate will be noisy"
        )

    pre_df, test_df, n_test = _split_case(case_df, pre_count)
    control_regions = sorted(r for r in case_df["region"].unique() if r != TEST_REGION)
    rng = np.random.default_rng(config.random_seed)

    method_fn = METHODS[config.method]
    null, alt_fn, meta = method_fn(
        pre_df, test_df, control_regions, n_test, config.n_simulations, rng
    )
    null = np.asarray(null, dtype=float)

    n_grid = 200
    effect_grid = np.linspace(config.mde_bounds[0], config.mde_bounds[1], n_grid)
    powers = np.full(n_grid, np.nan)
    ci_low = np.full(n_grid, np.nan)
    ci_high = np.full(n_grid, np.nan)
    failures_total = int(meta.get("failures", 0))
    alt_cache = {}

    def power_at(effect):
        """Estimated power for one effect (with CI)."""
        if effect in alt_cache:
            return alt_cache[effect]
        alt, fail = alt_fn(float(effect), config.effect_injection)
        failures_total_local = int(fail)
        alt = np.asarray(alt, dtype=float)
        valid = np.isfinite(alt)
        if not valid.any():
            result = (0.0, 0.0, 0.0, failures_total_local)
            alt_cache[effect] = result
            return result
        detected = _detected(null, alt[valid], config.side, config.alpha)
        power, lo, hi = power_with_ci(detected, config.alpha)
        result = (power, lo, hi, failures_total_local)
        alt_cache[effect] = result
        return result

    for i, e in enumerate(effect_grid):
        power, lo, hi, fail = power_at(float(e))
        powers[i] = power
        ci_low[i] = lo
        ci_high[i] = hi
        failures_total += fail

    null_threshold = _threshold(null, config.side, config.alpha)

    mde, reached, _, _ = find_mde(
        lambda e: power_at(float(e))[0],
        config.mde_bounds,
        config.target_power,
        config.mde_tolerance,
        n_grid=n_grid,
    )

    warnings = warnings + list(meta.get("warnings", []))
    if not reached:
        warnings.append(
            f"MDE not reached within bounds {tuple(config.mde_bounds)} at "
            f"target power {config.target_power:.0%}"
        )

    return PowerResult(
        method=config.method,
        detection_criterion=config.detection_criterion,
        effect_injection=config.effect_injection,
        effect_shape=config.effect_shape,
        side=config.side,
        alpha=config.alpha,
        target_power=config.target_power,
        n_simulations=config.n_simulations,
        random_seed=config.random_seed,
        effect_grid=effect_grid,
        power_curve=powers,
        power_ci_lower=ci_low,
        power_ci_upper=ci_high,
        null_threshold=float(null_threshold),
        null_mean=float(np.nanmean(null)),
        null_sd=float(np.nanstd(null)),
        mde=mde,
        mde_reached=reached,
        mde_bounds=tuple(config.mde_bounds),
        windows_available=int(meta.get("windows_available", 0)),
        windows_used=int(meta.get("windows_used", 0)),
        failures=int(failures_total),
        warnings=tuple(warnings),
    )


def _detected(null, alt, side, alpha):
    """Boolean detection array for alt against the null distribution."""
    lower, upper = critical_values(null, side, alpha)
    if side == "one_sided_positive":
        return alt > upper
    if side == "one_sided_negative":
        return alt < lower
    return (alt < lower) | (alt > upper)


def _threshold(null, side, alpha):
    """Report the (single) relevant null threshold for the side."""
    lower, upper = critical_values(null, side, alpha)
    if side == "one_sided_positive":
        return upper
    if side == "one_sided_negative":
        return lower
    return upper
