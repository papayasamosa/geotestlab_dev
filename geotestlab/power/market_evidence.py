"""Realistic market-shaped synthetic evidence for the power methodology spike.

Stage 4 (``test/power-methodology-realistic-evidence``). Builds synthetic data
shaped like real GeoTestLab markets and runs the candidate power methods
across them to produce decision evidence for methodology approval:

- **null calibration** — false-positive detection rate at effect 0 vs alpha;
- **power calibration** — estimated power at a reference effect vs the
  reference power computed from the KNOWN generative process (no model
  fitting, so the comparison isolates the method's estimation error);
- **MDE bias** — estimated MDE vs the reference MDE;
- **seed sensitivity** — spread of power / MDE across random seeds;
- **history sensitivity** — 52 / 104 / 156 weekly pre-periods;
- **fallback rates** — how often the explicit constant-mean fallback fires,
  by scenario and fit method;
- **runtime and failure modes** — wall time per run, incomplete / blocked /
  errored runs.

Scenarios are shaped like real markets: weekly and daily cadence, weekday
seasonality, multiple test regions, small and large control pools, collinear
and weak controls, low-volume KPIs, tracking outages (missing dates), high
autocorrelation, heteroskedasticity, seasonal residuals and an MDE that is
never reached within bounds.

This is **EVIDENCE for methodology approval**. It does NOT select a production
method, and it does NOT change the spike's result contract
(``geotestlab.power.models.PowerResult``).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from geotestlab.power.methods import fit_ar1, fit_counterfactual
from geotestlab.power.models import PowerConfig
from geotestlab.power.service import run_power_analysis
from geotestlab.power.synthetic import analytic_power

# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

MARKET_SCENARIOS = (
    "weekly_52",
    "weekly_104",
    "weekly_156",
    "daily_weekday",
    "low_volume",
    "high_autocorrelation",
    "heteroskedastic",
    "seasonal_residuals",
    "collinear_controls",
    "many_weak_controls",
    "duplicate_controls",
    "mde_not_reached",
)

# Reference-power Monte-Carlo defaults (deterministic; fixed seed).
REFERENCE_SEED = 12345
REFERENCE_SIMULATIONS = 20000


@dataclass
class MarketScenario:
    """One realistic market-shaped synthetic case plus its known truth."""

    name: str
    df: pd.DataFrame  # long frame: date, region, kpi (effect-free)
    pre_count: int
    test_regions: tuple
    control_regions: tuple
    truth: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def _stationary_ar1(n, rho, sigma_t, rng, seed_prev=None):
    """Stationary AR(1): e_t = rho*e_{t-1} + N(0, sigma_t[t]).

    The first value is drawn from the stationary variance so the whole series
    is a stationary AR(1) (the test-window sum then matches the reference
    process exactly, with no burn-in transient).
    """
    e = np.empty(n)
    if seed_prev is None:
        var0 = float(sigma_t[0] ** 2 / (1.0 - rho**2)) if rho**2 < 1.0 else sigma_t[0] ** 2
        e[0] = rng.normal(0.0, np.sqrt(var0))
    else:
        e[0] = seed_prev
    for t in range(1, n):
        e[t] = rho * e[t - 1] + rng.normal(0.0, sigma_t[t])
    return e


def generate_market_case(
    n_pre,
    n_test,
    freq="W",
    test_regions=("T1", "T2"),
    control_regions=("C1", "C2", "C3", "C4"),
    control_betas=None,
    test_coeffs=None,
    b0=100.0,
    rho=0.4,
    sigma=2.0,
    sigma_weekday=None,
    control_weekday_mult=None,
    test_weekday_offsets=None,
    heteroskedastic=False,
    season_amp=2.0,
    trend=0.02,
    control_noise_sd=1.0,
    collinear_pairs=(),
    exact_duplicates=(),
    missing_dates=(),
    seed=0,
):
    """Generate a realistic market-shaped synthetic case (long frame).

    Controls are ``c_j,t = base_j * wd_mult(weekday) + beta_j * signal_t +
    N(0, control_noise_sd)`` (optionally a collinear copy or an exact
    duplicate of another control). Each test region's counterfactual is
    ``cf_r,t = b0_r * wd_mult_r(weekday) + sum_j coeff_rj * c_j,t`` — an exact
    linear combination of the controls, plus (daily) a per-region additive
    weekday offset that is NOT spanned by the controls, so the fitted residual
    keeps a realistic seasonal component. The observed test KPI is the SUM of
    the test regions' series (matching the evaluation workflow's
    ``groupby(date).sum()`` aggregation) plus a stationary AR(1) noise process
    with per-period innovation sd ``sigma_t`` (optionally heteroskedastic or
    weekday-patterned).

    ``missing_dates`` are 0-based positions in the PRE-period that are dropped
    from every region (a tracking outage), so alignment reports them rather
    than silently misaligning.
    """
    rng = np.random.default_rng(seed)
    n_total = n_pre + n_test
    dates = pd.date_range("2024-01-01", periods=n_total, freq=freq)
    period = 52 if freq == "W" else 7
    t_idx = np.arange(n_total, dtype=float)
    signal = trend * t_idx + season_amp * np.sin(2 * np.pi * t_idx / period)
    weekdays = np.array([d.weekday() for d in dates])

    cbetas = control_betas or {r: 1.0 for r in control_regions}
    if test_coeffs is None:
        test_coeffs = {r: {c: 1.0 for c in control_regions} for r in test_regions}
    base = {r: 10.0 for r in control_regions}

    wd_mult = control_weekday_mult or {}
    controls = {}
    for r in control_regions:
        w = cbetas[r]
        noise = rng.normal(0.0, control_noise_sd, n_total)
        weekday_component = np.array([wd_mult.get(wd, 1.0) for wd in weekdays], dtype=float)
        controls[r] = base[r] * weekday_component + w * signal + noise

    # Collinear copies: C2 = C1 + tiny noise (ill-conditioned but full rank).
    for src, dst, noise_sd in collinear_pairs:
        controls[dst] = controls[src] + rng.normal(0.0, noise_sd, n_total)
    # Exact duplicates: C2 == C1 (rank-deficient by the explicit duplicate rule).
    for src, dst in exact_duplicates:
        controls[dst] = controls[src].copy()

    # Per-test-region counterfactual, innovation sd and AR(1) noise. The
    # counterfactual is an exact linear combination of the controls plus
    # (daily) a per-region additive weekday offset that the controls do NOT
    # span, so the fitted residual keeps a realistic seasonal component.
    test_offsets = test_weekday_offsets or {}
    cf = np.zeros(n_total)
    sigma_agg_t = np.zeros(n_total)
    rows = []
    for r in test_regions:
        coeff = test_coeffs[r]
        base_r = float(b0) * (1.0 + 0.1 * int(r[-1])) if r[-1].isdigit() else float(b0)
        cf_r = np.full(n_total, base_r)
        for c in control_regions:
            cf_r = cf_r + coeff.get(c, 0.0) * controls[c]
        off = test_offsets.get(r, {})
        if off:
            cf_r = cf_r + np.array([off.get(wd, 0.0) for wd in weekdays], dtype=float)
        # Per-region innovation sd (optionally heteroskedastic / weekday-patterned).
        sigma_r = np.full(n_total, float(sigma))
        if sigma_weekday:
            sigma_r = sigma_r * np.array(
                [sigma_weekday.get(wd, 1.0) for wd in weekdays], dtype=float
            )
        if heteroskedastic:
            scale = (np.abs(cf_r) / max(base_r, 1e-9)) ** 2
            sigma_r = sigma_r * np.maximum(scale, 0.1)
        e_r = _stationary_ar1(n_total, rho, sigma_r, rng)
        cf = cf + cf_r
        sigma_agg_t = sigma_agg_t + sigma_r**2
        for t in range(n_total):
            rows.append((dates[t], r, float(cf_r[t] + e_r[t])))
    sigma_agg_t = np.sqrt(sigma_agg_t)

    # No effect is injected (the harness reads the whole power curve from
    # simulation), so the data is always effect-free.
    for c in control_regions:
        for t in range(n_total):
            rows.append((dates[t], c, float(controls[c][t])))

    df = pd.DataFrame(rows, columns=["date", "region", "kpi"])
    if missing_dates:
        # A tracking outage = missing KPI values for every region on those
        # dates (the date rows stay, so pre/test split and alignment both
        # work; alignment reports the removed dates).
        outage_positions = {int(p) for p in missing_dates if int(p) < n_pre}
        outage_mask = np.zeros(n_total, dtype=bool)
        outage_mask[list(outage_positions)] = True
        outage_dates = dates[outage_mask]
        df.loc[df["date"].isin(outage_dates), "kpi"] = np.nan

    truth = {
        "cf": cf,
        "cf_sum_test": float(np.sum(cf[n_pre:])),
        "rho": float(rho),
        "sigma_agg_test": np.asarray(sigma_agg_t[n_pre:], dtype=float),
        "injection": "relative",
        "reference_effect": 5.0,
        "mde_bounds": (0.0, 50.0),
        "freq": freq,
        "n_pre": int(n_pre),
        "n_test": int(n_test),
        "description": "",
    }
    return df, truth


def build_market_scenario(name, seed=0) -> MarketScenario:
    """Build one named market scenario with its known truth precomputed."""
    if name not in MARKET_SCENARIOS:
        raise ValueError(f"unknown market scenario {name!r}; expected one of {MARKET_SCENARIOS}")

    common_coeffs = {
        "T1": {"C1": 1.5, "C2": 0.5, "C3": 1.0, "C4": 0.4},
        "T2": {"C1": 0.8, "C2": 1.2, "C3": 0.6, "C4": 1.1},
    }
    betas = {"C1": 1.0, "C2": 2.0, "C3": 1.5, "C4": 0.8}

    if name in ("weekly_52", "weekly_104", "weekly_156"):
        n_pre = {"weekly_52": 52, "weekly_104": 104, "weekly_156": 156}[name]
        df, truth = generate_market_case(
            n_pre=n_pre,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=2.0,
            season_amp=2.0,
            trend=0.02,
            seed=seed,
        )
        truth["reference_effect"] = 0.8  # same for all histories (process is identical)
        truth["description"] = (
            f"{n_pre} weekly pre-periods, 2 test regions, 4 controls, AR(1) rho=0.4, sigma=2"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=n_pre,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "daily_weekday":
        df, truth = generate_market_case(
            n_pre=52 * 7,
            n_test=14,
            freq="D",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=2.0,
            control_weekday_mult={0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.05, 5: 1.2, 6: 1.15},
            test_weekday_offsets={
                "T1": {0: 0.0, 1: 2.0, 2: 3.0, 3: 4.0, 4: 5.0, 5: 8.0, 6: 6.0},
                "T2": {0: 0.0, 1: 1.0, 2: 2.0, 3: 2.0, 4: 3.0, 5: 5.0, 6: 4.0},
            },
            missing_dates=(100, 101, 200, 305, 306, 340),
            seed=seed,
        )
        truth["reference_effect"] = 0.5
        truth["description"] = (
            "365 daily pre-periods, weekday seasonality (controls + test-specific "
            "offsets), tracking outages (6 missing dates), 2 test regions"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=52 * 7,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "low_volume":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2"),
            control_betas={"C1": 1.0, "C2": 1.5},
            test_coeffs={
                "T1": {"C1": 1.0, "C2": 0.5},
                "T2": {"C1": 0.6, "C2": 1.0},
            },
            b0=10.0,
            rho=0.3,
            sigma=0.5,
            seed=seed,
        )
        truth["injection"] = "absolute"
        truth["reference_effect"] = 5.0
        truth["mde_bounds"] = (0.0, 10.0)
        truth["description"] = "low-volume KPI (absolute injection; relative ill-defined)"
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2"),
            truth=truth,
        )

    if name == "high_autocorrelation":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.9,
            sigma=2.0,
            seed=seed,
        )
        truth["reference_effect"] = 2.0
        truth["description"] = "104 weekly pre-periods, high AR(1) autocorrelation rho=0.9"
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "heteroskedastic":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=1.5,
            heteroskedastic=True,
            seed=seed,
            season_amp=6.0,
        )
        truth["reference_effect"] = 0.8
        truth["description"] = (
            "104 weekly pre-periods, heteroskedastic noise (sd scales with level)"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "seasonal_residuals":
        df, truth = generate_market_case(
            n_pre=52 * 7,
            n_test=14,
            freq="D",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=1.5,
            sigma_weekday={0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.2, 5: 2.5, 6: 2.2},
            seed=seed,
        )
        truth["reference_effect"] = 0.5
        truth["description"] = (
            "365 daily pre-periods, seasonal residuals (weekend innovation sd ~2.5x)"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=52 * 7,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "collinear_controls":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=2.0,
            collinear_pairs=(("C1", "C2", 1e-3),),
            seed=seed,
        )
        truth["reference_effect"] = 0.8
        truth["description"] = (
            "104 weekly pre-periods, C2 is a near-duplicate of C1 (ill-conditioned, full rank)"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "many_weak_controls":
        controls = tuple(f"C{i}" for i in range(1, 9))
        weak_betas = {c: 0.5 for c in controls}
        weak_coeffs = {
            "T1": {c: 0.25 for c in controls},
            "T2": {c: 0.2 for c in controls},
        }
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=controls,
            control_betas=weak_betas,
            test_coeffs=weak_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=2.0,
            seed=seed,
        )
        truth["reference_effect"] = 0.8
        truth["description"] = "104 weekly pre-periods, 8 weak controls (small signal each)"
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=controls,
            truth=truth,
        )

    if name == "duplicate_controls":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.4,
            sigma=2.0,
            exact_duplicates=(("C1", "C2"),),
            seed=seed,
        )
        truth["reference_effect"] = 0.8
        truth["description"] = (
            "104 weekly pre-periods, C2 exactly duplicates C1 (rank rule -> "
            "constant-mean fallback for every fit method)"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    if name == "mde_not_reached":
        df, truth = generate_market_case(
            n_pre=104,
            n_test=12,
            freq="W",
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            control_betas=betas,
            test_coeffs=common_coeffs,
            b0=100.0,
            rho=0.99,
            sigma=8.5,
            seed=seed,
        )
        truth["reference_effect"] = 25.0
        truth["description"] = (
            "104 weekly pre-periods, near-unit-root AR(1) rho=0.99 with large "
            "noise: MDE never reaches 80% within 50% bounds"
        )
        return MarketScenario(
            name=name,
            df=df,
            pre_count=104,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            truth=truth,
        )

    raise ValueError(f"unhandled scenario {name!r}")


# ---------------------------------------------------------------------------
# Reference truth (known generative process — no model fitting)
# ---------------------------------------------------------------------------


def noise_sum_simulator(sigma_agg_test, rho, n_test):
    """Return ``fn(n_sim, rng) -> array`` of test-window noise sums from the
    KNOWN stationary AR(1) process (per-period innovation sd ``sigma_agg_test``).
    """

    def simulate(n_sim, rng):
        var0 = (
            float(sigma_agg_test[0] ** 2 / (1.0 - rho**2))
            if rho**2 < 1.0
            else float(sigma_agg_test[0] ** 2)
        )
        prev = rng.normal(0.0, np.sqrt(var0), size=n_sim)
        total = prev.copy()
        for t in range(1, n_test):
            prev = rho * prev + rng.normal(0.0, sigma_agg_test[t], size=n_sim)
            total = total + prev
        return total

    return simulate


def reference_null_sd(scenario, n_sim=REFERENCE_SIMULATIONS, seed=REFERENCE_SEED):
    """SD of the test-window noise total under the known generative process.

    Cached on the scenario truth (deterministic for the fixed reference seed),
    so the evidence harness never re-simulates the 20k reference sample per
    run."""
    cache_key = f"_reference_null_sd_{n_sim}_{seed}"
    if cache_key in scenario.truth:
        return float(scenario.truth[cache_key])
    sim = noise_sum_simulator(
        np.asarray(scenario.truth["sigma_agg_test"], dtype=float),
        float(scenario.truth["rho"]),
        int(scenario.truth["n_test"]),
    )
    rng = np.random.default_rng(seed)
    sd = float(np.std(sim(n_sim, rng), ddof=1))
    scenario.truth[cache_key] = sd
    return sd


def reference_power(
    scenario,
    effect,
    side="one_sided_positive",
    alpha=0.05,
    n_sim=REFERENCE_SIMULATIONS,
    seed=REFERENCE_SEED,
):
    """Reference power for ``effect`` from the known process (normal approx on
    the true null SD). ``effect`` is in the scenario's injection units."""
    sd = reference_null_sd(scenario, n_sim=n_sim, seed=seed)
    cf = float(scenario.truth["cf_sum_test"])
    direction = -1.0 if side == "one_sided_negative" else 1.0
    if scenario.truth["injection"] == "absolute":
        shift = direction * float(effect)
    else:
        shift = direction * cf * (float(effect) / 100.0)
    return float(analytic_power(cf, sd, shift, alpha, side))


def reference_mde(
    scenario, target_power=0.80, alpha=0.05, bounds=None, tol=0.5, n_grid=400, seed=REFERENCE_SEED
):
    """Reference MDE (the effect reaching ``target_power`` under the known
    process). Returns ``(mde, reached)``."""
    bounds = tuple(bounds or scenario.truth["mde_bounds"])
    lo, hi = bounds
    grid = np.linspace(float(lo), float(hi), n_grid)
    powers = np.array(
        [
            reference_power(scenario, float(e), side="one_sided_positive", alpha=alpha, seed=seed)
            for e in grid
        ]
    )
    above = powers >= target_power
    if not above.any():
        return None, False
    idx = int(np.argmax(above))
    a = grid[idx - 1] if idx > 0 else float(lo)
    b = float(grid[idx])
    while (b - a) > tol and (b - a) > 1e-12:
        m = (a + b) / 2.0
        if (
            reference_power(scenario, float(m), side="one_sided_positive", alpha=alpha, seed=seed)
            >= target_power
        ):
            b = m
        else:
            a = m
    return float(b), True


def _power_at(result, effect):
    """Interpolate ``result.power_curve`` at ``effect`` (None if incomplete)."""
    if result is None or len(result.power_curve) == 0:
        return None
    return float(
        np.interp(
            float(effect),
            np.asarray(result.effect_grid, dtype=float),
            np.asarray(result.power_curve, dtype=float),
        )
    )


# ---------------------------------------------------------------------------
# Evidence harness
# ---------------------------------------------------------------------------


def _noise_diagnostics(case, fit_method):
    """Re-fit the counterfactual to report residual noise diagnostics
    (rho_hat / sigma_hat) without changing the spike result contract."""
    dates = sorted(pd.to_datetime(pd.Series(case.df["date"].unique())))
    pre_dates = set(dates[: case.pre_count])
    pre_df = case.df[case.df["date"].isin(pre_dates)]
    fit = fit_counterfactual(pre_df, case.test_regions, case.control_regions, fit_method=fit_method)
    rho, sigma = fit_ar1(fit.residuals)
    return {
        "rho_estimate": float(rho),
        "sigma_estimate": float(sigma),
        "fit_status": fit.fit_status,
        "fallback_reason": fit.diagnostics.get("fallback_reason"),
        "matrix_rank": fit.diagnostics.get("matrix_rank"),
        "n_predictors": fit.diagnostics.get("n_predictors"),
        "condition_number": fit.diagnostics.get("condition_number"),
        "n_fit_observations": int(len(fit.residuals)),
    }


def _evidence_grid(bounds, n_points=17):
    """A sorted effect grid that is dense near zero (where the power curve is
    steepest) and coarser at the top of the bounds. Units follow the
    scenario's injection (relative % or absolute)."""
    lo, hi = float(bounds[0]), float(bounds[1])
    width = hi - lo
    # Fractions of the width; the first points resolve sub-1% effects.
    fracs = np.array(
        [
            0.0,
            0.0005,
            0.001,
            0.002,
            0.004,
            0.008,
            0.015,
            0.025,
            0.04,
            0.06,
            0.1,
            0.15,
            0.25,
            0.4,
            0.7,
            1.0,
        ]
    )
    grid = lo + fracs * width
    # Ensure the upper bound is included exactly.
    grid = np.unique(np.concatenate([grid, [hi]]))
    return tuple(float(v) for v in grid)


def run_market_evidence(
    scenario_names=None,
    methods=("model_simulation", "residual_simulation", "placebo_empirical"),
    fit_methods=("ols", "elastic_net", "lasso"),
    sides=("one_sided_positive",),
    seeds=(0, 1),
    n_sim=500,
    alpha=0.05,
    target_power=0.80,
):
    """Run the candidate methods across market scenarios; return JSON-safe
    evidence with per-run records and aggregated summaries. Deterministic
    (fixed seeds; no timestamps or paths)."""
    names = list(scenario_names or MARKET_SCENARIOS)
    scenarios = {n: build_market_scenario(n) for n in names}
    runs = []
    for name in names:
        sc = scenarios[name]
        grid = _evidence_grid(sc.truth["mde_bounds"])
        for method in methods:
            for fm in fit_methods:
                for side in sides:
                    for seed in seeds:
                        runs.append(
                            _run_one(
                                sc, method, fm, side, int(seed), n_sim, grid, alpha, target_power
                            )
                        )
    return {
        "config": {
            "scenario_names": names,
            "methods": list(methods),
            "fit_methods": list(fit_methods),
            "sides": list(sides),
            "seeds": [int(s) for s in seeds],
            "n_simulations": int(n_sim),
            "effect_grid_points": len(grid),
            "alpha": float(alpha),
            "target_power": float(target_power),
            "reference_seed": REFERENCE_SEED,
            "reference_simulations": REFERENCE_SIMULATIONS,
        },
        "scenarios": [
            {
                "name": n,
                "description": scenarios[n].truth.get("description", ""),
                "pre_count": int(scenarios[n].pre_count),
                "test_regions": list(scenarios[n].test_regions),
                "control_regions": list(scenarios[n].control_regions),
                "injection": scenarios[n].truth["injection"],
                "reference_effect": float(scenarios[n].truth["reference_effect"]),
                "mde_bounds": [float(v) for v in scenarios[n].truth["mde_bounds"]],
                "cf_sum_test": float(scenarios[n].truth["cf_sum_test"]),
                "true_rho": float(scenarios[n].truth["rho"]),
                "reference_null_sd": reference_null_sd(scenarios[n]),
                "reference_power": reference_power(
                    scenarios[n], float(scenarios[n].truth["reference_effect"])
                ),
                "reference_mde": reference_mde(
                    scenarios[n], target_power=target_power, alpha=alpha
                )[0],
                "reference_mde_reached": reference_mde(
                    scenarios[n], target_power=target_power, alpha=alpha
                )[1],
            }
            for n in names
        ],
        "runs": runs,
        "summaries": summarise_evidence(runs, names),
        "totals": _totals(runs),
    }


def _run_one(scenario, method, fit_method, side, seed, n_sim, effect_grid, alpha, target_power):
    bounds = tuple(scenario.truth["mde_bounds"])
    config = PowerConfig(
        method=method,
        detection_criterion="interval_excludes_zero",
        effect_injection=scenario.truth["injection"],
        effect_shape="step",
        side=side,
        alpha=alpha,
        target_power=target_power,
        n_simulations=n_sim,
        random_seed=seed,
        mde_bounds=bounds,
        mde_tolerance=0.5,
        min_placebo_windows=5,
        test_regions=scenario.test_regions,
        control_regions=scenario.control_regions,
        fit_method=fit_method,
        effect_grid=effect_grid,
    )
    t0 = time.perf_counter()
    error = None
    try:
        res = run_power_analysis(scenario.df, scenario.pre_count, config)
    except Exception as exc:  # record failure modes, never abort the matrix
        res = None
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - t0

    ref_effect = float(scenario.truth["reference_effect"])
    rec = {
        "scenario": scenario.name,
        "method": method,
        "fit_method": fit_method,
        "side": side,
        "seed": seed,
        "runtime_s": float(elapsed),
        "error": error,
        "reference_power": reference_power(scenario, ref_effect, side=side, alpha=alpha),
    }
    if res is not None:
        rec.update(
            {
                "completed": bool(res.completed),
                "fit_status": res.fit_status,
                "fit_method_used": res.fit_method,
                "fallback_reason": res.matrix_diagnostics.get("fallback_reason"),
                "matrix_rank": res.matrix_diagnostics.get("matrix_rank"),
                "n_predictors": res.matrix_diagnostics.get("n_predictors"),
                "condition_number": res.matrix_diagnostics.get("condition_number"),
                "power_at_zero": _power_at(res, 0.0),
                "power_at_reference": _power_at(res, ref_effect),
                "mde": float(res.mde) if res.mde is not None else None,
                "mde_reached": bool(res.mde_reached),
                "null_sd": float(res.null_sd) if np.isfinite(res.null_sd) else None,
                "windows_available": int(res.windows_available),
                "windows_used": int(res.windows_used),
                "failures": int(res.failures),
                "n_errors": len(res.errors),
                "n_blockers": len(res.blockers),
                "n_warnings": len(res.warnings),
                "blockers": list(res.blockers),
                "errors": list(res.errors),
            }
        )
        rec["noise_diagnostics"] = _noise_diagnostics(scenario, fit_method)
    else:
        rec.update(
            {
                "completed": False,
                "fit_status": None,
                "fit_method_used": None,
                "fallback_reason": None,
                "matrix_rank": None,
                "n_predictors": None,
                "condition_number": None,
                "power_at_zero": None,
                "power_at_reference": None,
                "mde": None,
                "mde_reached": False,
                "null_sd": None,
                "windows_available": 0,
                "windows_used": 0,
                "failures": 0,
                "n_errors": 0,
                "n_blockers": 0,
                "n_warnings": 0,
                "blockers": [],
                "errors": [],
                "noise_diagnostics": _noise_diagnostics(scenario, fit_method),
            }
        )
    return rec


def _stats(values):
    """mean / std (NaN-safe) over a list of floats-or-None."""
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if not vals:
        return {"n": 0, "mean": None, "std": None}
    arr = np.asarray(vals, dtype=float)
    return {
        "n": int(len(arr)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
    }


def summarise_evidence(runs, scenario_names):
    """Aggregate per-run evidence by scenario / method / fit method (positive
    side), a per-scenario collapsed view, and a per-side view (for the side
    matrix)."""
    summaries = {}
    sides = sorted({r["side"] for r in runs})
    for name in scenario_names:
        by = {}
        for method in ("model_simulation", "residual_simulation", "placebo_empirical"):
            for fm in ("ols", "elastic_net", "lasso"):
                key = f"{method}|{fm}"
                sub = [
                    r
                    for r in runs
                    if r["scenario"] == name
                    and r["method"] == method
                    and r["fit_method"] == fm
                    and r["side"] == "one_sided_positive"
                ]
                if not sub:
                    continue
                by[key] = _summarise_cell(sub)
        by_side = {}
        for side in sides:
            for method in ("model_simulation", "residual_simulation", "placebo_empirical"):
                sub = [
                    r
                    for r in runs
                    if r["scenario"] == name and r["side"] == side and r["method"] == method
                ]
                if not sub:
                    continue
                by_side[f"{side}|{method}"] = _summarise_cell(sub)
        summaries[name] = {
            "cells": by,
            "by_side": by_side,
            "collapsed": _summarise_cell(
                [r for r in runs if r["scenario"] == name and r["side"] == "one_sided_positive"]
            ),
        }
    return summaries


def _summarise_cell(runs):
    ok = [r for r in runs if r.get("completed") and not r.get("error")]
    n_ok = len(ok)
    ref_power = [r["reference_power"] for r in ok if r.get("reference_power") is not None]
    ref_power = ref_power[0] if ref_power else None

    power_at_zero = _stats([r.get("power_at_zero") for r in ok])
    power_at_ref = _stats([r.get("power_at_reference") for r in ok])
    mde = _stats([r.get("mde") for r in ok])
    rho_hat = _stats([r.get("noise_diagnostics", {}).get("rho_estimate") for r in ok])
    sigma_hat = _stats([r.get("noise_diagnostics", {}).get("sigma_estimate") for r in ok])
    null_sd = _stats([r.get("null_sd") for r in ok])

    return {
        "n_runs": len(runs),
        "n_completed": n_ok,
        "n_errored": sum(1 for r in runs if r.get("error")),
        "n_incomplete": sum(1 for r in runs if not r.get("error") and not r.get("completed")),
        "null_calibration_mean": power_at_zero["mean"],
        "null_calibration_std": power_at_zero["std"],
        "null_calibration_deviation": (
            power_at_zero["mean"] - 0.05 if power_at_zero["mean"] is not None else None
        ),
        "power_at_reference_mean": power_at_ref["mean"],
        "power_at_reference_std": power_at_ref["std"],
        "power_bias_vs_reference": (
            power_at_ref["mean"] - ref_power
            if power_at_ref["mean"] is not None and ref_power is not None
            else None
        ),
        "reference_power": ref_power,
        "mde_mean": mde["mean"],
        "mde_std": mde["std"],
        "mde_reached_rate": (sum(1 for r in ok if r.get("mde_reached")) / n_ok if n_ok else None),
        "rho_hat_mean": rho_hat["mean"],
        "sigma_hat_mean": sigma_hat["mean"],
        "null_sd_mean": null_sd["mean"],
        "fallback_rate": (sum(1 for r in ok if r.get("fallback_reason")) / n_ok if n_ok else None),
        "runtime_total_s": float(sum(r.get("runtime_s", 0.0) for r in runs)),
        "runtime_mean_s": float(np.mean([r.get("runtime_s", 0.0) for r in runs])) if runs else 0.0,
    }


def _totals(runs):
    return {
        "total_runs": len(runs),
        "n_completed": sum(1 for r in runs if r.get("completed")),
        "n_errored": sum(1 for r in runs if r.get("error")),
        "n_incomplete": sum(1 for r in runs if not r.get("error") and not r.get("completed")),
        "n_fallback": sum(1 for r in runs if r.get("fallback_reason")),
        "total_runtime_s": float(sum(r.get("runtime_s", 0.0) for r in runs)),
    }


def combine_evidence(*parts):
    """Merge several evidence dicts into one report (all runs, per-part
    summaries preserved under ``parts``)."""
    runs = []
    for p in parts:
        runs.extend(p["runs"])
    all_names = []
    for p in parts:
        for s in p["scenarios"]:
            if s["name"] not in all_names:
                all_names.append(s["name"])
    return {
        "parts": [
            {
                "config": p["config"],
                "totals": p["totals"],
            }
            for p in parts
        ],
        "config": parts[0]["config"],
        "scenarios": parts[0]["scenarios"],
        "runs": runs,
        "summaries": summarise_evidence(runs, all_names),
        "totals": _totals(runs),
    }


def write_evidence_report(path, evidence):
    """Write a JSON-safe evidence report (utf-8, indent 2)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True)
        fh.write("\n")


def strip_timing(evidence):
    """Deep copy of the evidence with per-run runtime removed.

    Wall-clock runtime is inherently non-deterministic, so the committed
    evidence report (and any byte-for-byte comparison) excludes it; runtime is
    reported separately in the methodology document.
    """
    import copy

    out = copy.deepcopy(evidence)
    for r in out.get("runs", []):
        r.pop("runtime_s", None)
    out.get("totals", {}).pop("total_runtime_s", None)
    # combine_evidence keeps per-part totals; strip runtime there too.
    for part in out.get("parts", []):
        part.get("totals", {}).pop("total_runtime_s", None)
    for s in out.get("summaries", {}).values():
        for section in (
            s.get("collapsed"),
            *s.get("cells", {}).values(),
            *s.get("by_side", {}).values(),
        ):
            if isinstance(section, dict):
                section.pop("runtime_total_s", None)
                section.pop("runtime_mean_s", None)
    return out
