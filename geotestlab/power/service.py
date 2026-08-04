"""Power-analysis spike service (pure; no Streamlit).

Runs one of the candidate methods against an explicitly selected design (test
regions, control regions, pre-period, optional planned test dates) and returns
a typed :class:`PowerResult` with every PA-FR5 output: power curve, conditional
power uncertainty (Clopper-Pearson on the alternative detection count), MDE,
simulation count, seed, detection criterion, windows used, failures, warnings,
errors, blockers and structured fit/matrix diagnostics.

The spike contract (corrected):
- effect magnitude is always non-negative; direction is controlled by ``side``;
- only implemented detection criteria are accepted (``interval_excludes_zero``,
  and ``empirical_placebo_threshold`` for the placebo method only);
- only ``step`` effect shape is implemented in the simulation path;
- threshold calibration, alternative simulation and diagnostics use independent
  random streams;
- rank-deficient / ill-conditioned fits fall back to a constant mean with the
  reason recorded and a structured warning;
- insufficient placebo/residual evidence produces an explicit incomplete result
  with no MDE.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.power.detection import critical_values, validate_detection_criterion
from geotestlab.power.mde import find_mde
from geotestlab.power.methods import FIT_METHOD_NAMES, METHODS
from geotestlab.power.models import (
    EFFECT_INJECTIONS,
    METHODOLOGY_VERSION,
    SIDES,
    PowerConfig,
    PowerResult,
    validate_effect_shape,
)
from geotestlab.power.uncertainty import power_with_ci


def run_power_analysis(case_df, pre_count, config: PowerConfig) -> PowerResult:
    """Run the power spike for one explicitly selected design."""
    validate_detection_criterion(config.detection_criterion, method=config.method)
    if config.method not in METHODS:
        raise ValueError(f"Unknown method {config.method!r}; expected one of {list(METHODS)}")
    if config.fit_method not in FIT_METHOD_NAMES:
        raise ValueError(
            f"Unknown fit method {config.fit_method!r}; expected one of {FIT_METHOD_NAMES}"
        )
    if config.effect_injection not in EFFECT_INJECTIONS:
        raise ValueError(f"Unknown effect injection {config.effect_injection!r}")
    if config.side not in SIDES:
        raise ValueError(f"Unknown side {config.side!r}")
    validate_effect_shape(config.effect_shape)
    if not config.test_regions:
        raise ValueError("PowerConfig.test_regions must name the test region(s)")
    if not config.control_regions:
        raise ValueError("PowerConfig.control_regions must name the control region(s)")
    _validate_region_sets(config.test_regions, config.control_regions, case_df)

    warnings: list[str] = []
    errors: list[str] = []
    blockers: list[str] = []

    minimum_history_status = "ok"
    if pre_count < config.min_historical_periods:
        minimum_history_status = "insufficient"
        warnings.append(
            f"pre-period has {pre_count} periods (< recommended minimum "
            f"{config.min_historical_periods})"
        )
    if config.n_simulations < config.min_simulations:
        warnings.append(
            f"n_simulations={config.n_simulations} (< recommended minimum "
            f"{config.min_simulations}); power estimate will be noisy"
        )

    pre_df, test_df, n_test = _split_case(case_df, pre_count, config)
    if n_test <= 0:
        errors.append("no test dates available (planned duration is empty)")
        blockers.append("planned test duration must contain at least one date")
        return _incomplete_result(
            config, warnings, errors, blockers, minimum_history_status, "not_applicable"
        )

    rng = np.random.default_rng(config.random_seed)
    method_fn = METHODS[config.method]
    if config.method in ("model_simulation", "residual_simulation"):
        cal_null, alt_fn, meta = method_fn(
            pre_df,
            test_df,
            config.test_regions,
            config.control_regions,
            n_test,
            config.n_simulations,
            rng,
            fit_method=config.fit_method,
        )
    else:
        cal_null, alt_fn, meta = method_fn(
            pre_df,
            test_df,
            config.test_regions,
            config.control_regions,
            n_test,
            config.n_simulations,
            rng,
        )
    cal_null = np.asarray(cal_null, dtype=float)

    # Minimum-window enforcement for empirical/bootstrap methods: insufficient
    # placebo/residual evidence must produce an explicit incomplete result.
    minimum_window_status = "not_applicable"
    if config.method in ("placebo_empirical", "residual_simulation"):
        windows = int(meta.get("windows_available", 0))
        if windows < config.min_placebo_windows:
            minimum_window_status = "insufficient"
            msg = (
                f"{config.method} has only {windows} windows "
                f"(< minimum {config.min_placebo_windows}); result is incomplete"
            )
            errors.append(msg)
            blockers.append(msg)
            return _incomplete_result(
                config,
                warnings,
                errors,
                blockers,
                minimum_history_status,
                minimum_window_status,
                windows_available=windows,
                windows_used=int(meta.get("windows_used", 0)),
            )
        minimum_window_status = "ok"

    n_grid = 200
    effect_grid = np.linspace(config.mde_bounds[0], config.mde_bounds[1], n_grid)
    powers = np.full(n_grid, np.nan)
    ci_low = np.full(n_grid, np.nan)
    ci_high = np.full(n_grid, np.nan)
    failures_total = int(meta.get("failures", 0))
    alt_cache = {}

    def power_at(effect):
        """Estimated power (and CI) for one effect, from an independent
        alternative sample detected against the calibration null."""
        if effect in alt_cache:
            return alt_cache[effect]
        alt, fail = alt_fn(float(effect), config.effect_injection, config.side)
        failures_total_local = int(fail)
        alt = np.asarray(alt, dtype=float)
        valid = np.isfinite(alt)
        if not valid.any():
            result = (0.0, 0.0, 0.0, failures_total_local)
            alt_cache[effect] = result
            return result
        detected = _detected(cal_null, alt[valid], config.side, config.alpha)
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

    null_threshold = _threshold(cal_null, config.side, config.alpha)
    null_mean = float(meta.get("null_mean", np.nanmean(cal_null)))
    null_sd = float(meta.get("null_sd", np.nanstd(cal_null)))

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
        null_mean=null_mean,
        null_sd=null_sd,
        mde=mde,
        mde_reached=reached,
        mde_bounds=tuple(config.mde_bounds),
        windows_available=int(meta.get("windows_available", 0)),
        windows_used=int(meta.get("windows_used", 0)),
        failures=int(failures_total),
        warnings=tuple(warnings),
        completed=True,
        fit_status=str(meta.get("fit_status", "not_run")),
        fit_method=str(meta.get("fit_method", config.method)),
        matrix_diagnostics=dict(meta.get("matrix_diagnostics", {})),
        calibration_simulations=int(meta.get("calibration_simulations", 0)),
        detection_simulations=int(meta.get("detection_simulations", 0)),
        minimum_history_status=minimum_history_status,
        minimum_window_status=minimum_window_status,
        methodology_version=METHODOLOGY_VERSION,
        errors=tuple(errors),
        blockers=tuple(blockers),
    )


def _split_case(case_df, pre_count, config):
    """Split into pre/test by pre_count or explicit planned test dates."""
    all_dates = pd.to_datetime(pd.Series(sorted(case_df["date"].unique()))).to_numpy()
    if config.test_dates:
        test_dates = set(pd.to_datetime(pd.Series(list(config.test_dates))).to_numpy())
        pre_dates = set(all_dates) - test_dates
    else:
        pre_dates = set(all_dates[:pre_count])
        test_dates = set(all_dates[pre_count:])
    pre_df = case_df[case_df["date"].isin(pre_dates)].copy()
    test_df = case_df[case_df["date"].isin(test_dates)].copy()
    return pre_df, test_df, len(test_dates)


def _validate_region_sets(test_regions, control_regions, case_df):
    overlap = set(test_regions) & set(control_regions)
    if overlap:
        raise ValueError(f"regions cannot be both test and control: {sorted(overlap)}")
    available = set(case_df["region"].unique())
    missing = [r for r in list(test_regions) + list(control_regions) if r not in available]
    if missing:
        raise ValueError(f"regions not present in data: {sorted(missing)}")


def _incomplete_result(
    config,
    warnings,
    errors,
    blockers,
    minimum_history_status,
    minimum_window_status,
    windows_available=0,
    windows_used=0,
):
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
        effect_grid=np.array([]),
        power_curve=np.array([]),
        power_ci_lower=np.array([]),
        power_ci_upper=np.array([]),
        null_threshold=float("nan"),
        null_mean=float("nan"),
        null_sd=float("nan"),
        mde=None,
        mde_reached=False,
        mde_bounds=tuple(config.mde_bounds),
        windows_available=int(windows_available),
        windows_used=int(windows_used),
        failures=0,
        warnings=tuple(warnings),
        completed=False,
        fit_status="not_run",
        fit_method=config.method,
        matrix_diagnostics={},
        calibration_simulations=0,
        detection_simulations=0,
        minimum_history_status=minimum_history_status,
        minimum_window_status=minimum_window_status,
        methodology_version=METHODOLOGY_VERSION,
        errors=tuple(errors),
        blockers=tuple(blockers),
    )


def _detected(cal_null, alt, side, alpha):
    """Boolean detection array for alt against the calibration null."""
    lower, upper = critical_values(cal_null, side, alpha)
    if side == "one_sided_positive":
        return alt > upper
    if side == "one_sided_negative":
        return alt < lower
    return (alt < lower) | (alt > upper)


def _threshold(cal_null, side, alpha):
    """Report the (single) relevant null threshold for the side."""
    lower, upper = critical_values(cal_null, side, alpha)
    if side == "one_sided_negative":
        return lower
    return upper
