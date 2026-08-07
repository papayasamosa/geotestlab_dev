"""Stage 5: power-methodology evidence version 2 (multi-seed statistical study).

Extends the Stage 4 market-evidence harness (``geotestlab.power.market_evidence``,
a single implicit data-generation seed) along two axes:

1. **Multiple independent data-generation seeds** crossed with multiple
   Monte-Carlo simulation seeds, for every core market scenario -- so bias
   and false-rate statistics reflect variation across independently
   generated synthetic markets, not just Monte-Carlo noise on one dataset.
2. **A safety-scenario suite** covering categories the core 12 market
   scenarios do not exercise (partial test-region missingness, duplicate
   region-date keys, irrelevant controls, a nonlinear counterfactual, a
   structural break) -- evaluated as pass/fail SAFETY-GATE checks (does the
   result correctly block or complete), not power-bias evidence, since
   these scenarios deliberately break the assumptions the analytic
   reference power/MDE would need.

This module produces DECISION EVIDENCE ONLY. It does not change methodology
approval status (still "For methodology approval" in
``docs/spikes/power-analysis-methodology.md``) and defines PROPOSED, not
approved, acceptance thresholds.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from geotestlab.power.market_evidence import (
    MARKET_SCENARIOS,
    MarketScenario,
    _evidence_grid,
    _run_one,
    build_market_scenario,
    generate_market_case,
    reference_mde,
    reference_power,
)
from geotestlab.power.models import METHODOLOGY_VERSION

EVIDENCE_SUITE_VERSION = "2.0.0"

# Data-generation seeds (independent synthetic markets) x Monte-Carlo
# simulation seeds (independent random streams over the SAME market).
DEFAULT_DATA_SEEDS = (0, 1, 2)
DEFAULT_SIM_SEEDS = (0, 1)
DEFAULT_N_SIM = 500

# Scenarios the current AR(1) method is expected to BLOCK outright (Stage 3
# safety gates), used to compute the false-supported rate: a "supported"
# (completed=True) result on one of these is a false positive by
# construction, regardless of the specific effect/seed.
EXPECTED_BLOCKED_CORE_SCENARIOS = frozenset(
    {"weekly_52", "daily_weekday", "seasonal_residuals", "heteroskedastic", "mde_not_reached"}
)

# ---------------------------------------------------------------------------
# Proposed (NOT approved) acceptance thresholds.
#
# These are DECISION EVIDENCE for the methodology-approval gate, calibrated
# against this evidence suite's own findings. They are not enforced by any
# code path and carry no authority until an explicit product-owner approval
# converts the corresponding ADR from Proposed to Approved (see Stage 6).
# ---------------------------------------------------------------------------
PROPOSED_ACCEPTANCE_THRESHOLDS = {
    "null_calibration_abs_error": 0.02,  # |power_at_zero - alpha|
    "power_bias_abs_mean": 0.05,  # mean |power bias| over supported scenarios
    "power_bias_abs_worst_case": 0.15,  # worst single supported-scenario bias
    "mde_bias_relative": 0.25,  # |mde - reference_mde| / reference_mde
    "false_supported_rate": 0.0,  # a scenario this method must block, reported supported
    "false_mde_rate": 0.05,  # mde_reached=True while the reference MDE is not reached
    "seed_sensitivity_power_std": 0.05,  # std of power_at_reference across seeds
    "runtime_p95_seconds": 5.0,  # p95 per-run wall-clock runtime
}


# ---------------------------------------------------------------------------
# Additional safety-scenario suite (pass/fail, not power-bias evidence)
# ---------------------------------------------------------------------------

_BETAS = {"C1": 1.0, "C2": 2.0, "C3": 1.5, "C4": 0.8}
_COEFFS = {
    "T1": {"C1": 1.5, "C2": 0.5, "C3": 1.0, "C4": 0.4},
    "T2": {"C1": 0.8, "C2": 1.2, "C3": 0.6, "C4": 1.1},
}


def _base_weekly_case(seed):
    return generate_market_case(
        n_pre=120,
        n_test=12,
        freq="W",
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4"),
        control_betas=_BETAS,
        test_coeffs=_COEFFS,
        b0=100.0,
        rho=0.4,
        sigma=2.0,
        season_amp=2.0,
        trend=0.02,
        seed=seed,
    )


def build_test_region_partial_missingness_scenario(seed=0):
    """T2 (one of two selected test regions) is missing on 5 pre-period
    dates T1 still reports -- the fixed test-region composition (Stage 2)
    must exclude those dates from the retained pre-period, never silently
    sum whichever test region is available."""
    df, truth = _base_weekly_case(seed)
    dates = sorted(pd.to_datetime(pd.Series(df["date"].unique())))
    drop_dates = set(dates[20:25])
    df = df[~((df["region"] == "T2") & (df["date"].isin(drop_dates)))]
    truth["reference_effect"] = 0.8
    truth["description"] = (
        "120 weekly pre-periods, T2 missing on 5 dates T1 still reports "
        "(fixed test-region composition excludes those dates)"
    )
    return MarketScenario(
        name="test_region_partial_missingness",
        df=df,
        pre_count=120,
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4"),
        truth=truth,
    )


def build_duplicate_keys_scenario(seed=0):
    """5 duplicate (region, date) rows on a selected control -- must block
    outright (Stage 2), never resolved by whichever row a pivot keeps."""
    df, truth = _base_weekly_case(seed)
    dup = df[df["region"] == "C1"].iloc[:5].copy()
    df = pd.concat([df, dup], ignore_index=True)
    truth["reference_effect"] = 0.8
    truth["description"] = (
        "120 weekly pre-periods with 5 duplicate (region, date) keys on a "
        "selected control -- must block, never resolved by row order"
    )
    return MarketScenario(
        name="duplicate_keys",
        df=df,
        pre_count=120,
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4"),
        truth=truth,
    )


def build_irrelevant_controls_scenario(seed=0):
    """3 pure-noise controls with NO relationship to either test region,
    alongside the 4 real informative ones -- evidence for how the fit
    method handles irrelevant predictors (never a blocking condition by
    itself)."""
    df, truth = _base_weekly_case(seed)
    rng = np.random.default_rng(seed + 7001)
    dates = sorted(pd.to_datetime(pd.Series(df["date"].unique())))
    extra_rows = []
    for name in ("J1", "J2", "J3"):
        junk = rng.normal(0.0, 5.0, len(dates)) + 20.0
        for d, v in zip(dates, junk, strict=True):
            extra_rows.append({"date": d, "region": name, "kpi": float(v)})
    df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)
    truth["reference_effect"] = 0.8
    truth["description"] = (
        "120 weekly pre-periods, 3 pure-noise controls with no relationship "
        "to either test region, alongside the 4 real informative controls"
    )
    return MarketScenario(
        name="irrelevant_controls_market",
        df=df,
        pre_count=120,
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4", "J1", "J2", "J3"),
        truth=truth,
    )


def build_nonlinear_counterfactual_scenario(seed=0):
    """T1's true relationship to C1 is quadratic, not linear -- the linear
    AR(1) method is structurally blind to this; evidence for how far the
    reported power/MDE drift from the (linear) reference under this
    misspecification."""
    df, truth = _base_weekly_case(seed)
    dates = sorted(pd.to_datetime(pd.Series(df["date"].unique())))
    c1 = df[df["region"] == "C1"].sort_values("date")["kpi"].to_numpy()
    gamma = 0.1
    delta = gamma * (c1 - np.mean(c1)) ** 2
    mask = df["region"] == "T1"
    idx = df.index[mask]
    ordered = df.loc[idx].sort_values("date").index
    df = df.copy()
    df.loc[ordered, "kpi"] = df.loc[ordered, "kpi"].to_numpy() + delta
    truth["reference_effect"] = 0.8
    truth["description"] = (
        "120 weekly pre-periods, T1's true relationship to C1 is quadratic "
        "(the linear AR(1) method is structurally blind to this)"
    )
    return MarketScenario(
        name="nonlinear_counterfactual_market",
        df=df,
        pre_count=120,
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4"),
        truth=truth,
    )


def build_structural_break_scenario(seed=0):
    """T1's coefficient on C1 jumps discretely partway through the
    pre-period (not a gradual drift) -- a single static linear fit over the
    whole pre-period cannot capture either regime correctly."""
    df, truth = _base_weekly_case(seed)
    dates = sorted(pd.to_datetime(pd.Series(df["date"].unique())))
    c1 = df[df["region"] == "C1"].sort_values("date")["kpi"].to_numpy()
    t = np.arange(len(dates), dtype=float)
    break_point = len(dates) * 2 // 3
    extra_coef = np.where(t < break_point, 0.0, 1.2)
    delta = extra_coef * c1
    mask = df["region"] == "T1"
    idx = df.index[mask]
    ordered = df.loc[idx].sort_values("date").index
    df = df.copy()
    df.loc[ordered, "kpi"] = df.loc[ordered, "kpi"].to_numpy() + delta
    truth["reference_effect"] = 0.8
    truth["description"] = (
        "120 weekly pre-periods, T1's coefficient on C1 jumps discretely "
        "2/3 of the way through the pre-period (not a gradual drift)"
    )
    return MarketScenario(
        name="structural_break_market",
        df=df,
        pre_count=120,
        test_regions=("T1", "T2"),
        control_regions=("C1", "C2", "C3", "C4"),
        truth=truth,
    )


ADDITIONAL_SAFETY_SCENARIOS = (
    "test_region_partial_missingness",
    "duplicate_keys",
    "irrelevant_controls_market",
    "nonlinear_counterfactual_market",
    "structural_break_market",
)

# Whether the current method is EXPECTED to block each additional safety
# scenario outright. False for scenarios that are evidence about a fit
# method's behaviour, not a blocking condition.
ADDITIONAL_SCENARIO_EXPECTED_BLOCKED = {
    "test_region_partial_missingness": False,  # excluded dates, not a block
    "duplicate_keys": True,
    "irrelevant_controls_market": False,
    "nonlinear_counterfactual_market": False,
    "structural_break_market": False,
}

_ADDITIONAL_BUILDERS = {
    "test_region_partial_missingness": build_test_region_partial_missingness_scenario,
    "duplicate_keys": build_duplicate_keys_scenario,
    "irrelevant_controls_market": build_irrelevant_controls_scenario,
    "nonlinear_counterfactual_market": build_nonlinear_counterfactual_scenario,
    "structural_break_market": build_structural_break_scenario,
}


def build_v2_scenario(name, seed=0):
    """Build a named scenario from either the core suite or the additional
    safety-scenario suite."""
    if name in _ADDITIONAL_BUILDERS:
        return _ADDITIONAL_BUILDERS[name](seed=seed)
    return build_market_scenario(name, seed=seed)


# ---------------------------------------------------------------------------
# Multi-seed evidence run
# ---------------------------------------------------------------------------


def run_evidence_v2(
    scenario_names=None,
    additional_scenario_names=ADDITIONAL_SAFETY_SCENARIOS,
    methods=("model_simulation", "residual_simulation"),
    fit_methods=("ols",),
    side="one_sided_positive",
    data_seeds=DEFAULT_DATA_SEEDS,
    sim_seeds=DEFAULT_SIM_SEEDS,
    n_sim=DEFAULT_N_SIM,
    alpha=0.05,
    target_power=0.80,
):
    """Run the core scenario suite across multiple data-generation seeds x
    simulation seeds, plus the additional safety-scenario suite (one
    simulation seed per data seed -- pass/fail safety-gate checks, not
    power-bias evidence). Returns a JSON-safe dict with per-run records, the
    additional-scenario pass/fail table, and the aggregate v2 summary.
    """
    core_names = list(scenario_names or MARKET_SCENARIOS)
    runs = []
    reference_cache = {}
    for data_seed in data_seeds:
        for name in core_names:
            sc = build_market_scenario(name, seed=data_seed)
            grid = _evidence_grid(sc.truth["mde_bounds"])
            ref_effect = float(sc.truth["reference_effect"])
            ref_power = reference_power(sc, ref_effect, side=side, alpha=alpha)
            ref_mde, ref_mde_reached = reference_mde(sc, target_power=target_power, alpha=alpha)
            reference_cache[(name, int(data_seed))] = {
                "reference_power": ref_power,
                "reference_mde": ref_mde,
                "reference_mde_reached": ref_mde_reached,
            }
            loop_fits_by_method = {
                m: (("n/a",) if m == "placebo_empirical" else fit_methods) for m in methods
            }
            for method in methods:
                for fm in loop_fits_by_method[method]:
                    for sim_seed in sim_seeds:
                        rec = _run_one(
                            sc, method, fm, side, int(sim_seed), n_sim, grid, alpha, target_power
                        )
                        rec["data_seed"] = int(data_seed)
                        rec["reference_mde"] = ref_mde
                        rec["reference_mde_reached"] = bool(ref_mde_reached)
                        runs.append(rec)

    safety_runs = []
    for name in additional_scenario_names:
        for data_seed in data_seeds:
            sc = build_v2_scenario(name, seed=data_seed)
            grid = _evidence_grid(sc.truth["mde_bounds"])
            sim_seed = sim_seeds[0]
            rec = _run_one(
                sc, "model_simulation", "ols", side, int(sim_seed), n_sim, grid, alpha, target_power
            )
            rec["data_seed"] = int(data_seed)
            rec["expected_blocked"] = ADDITIONAL_SCENARIO_EXPECTED_BLOCKED[name]
            rec["safety_correct"] = bool(
                rec["completed"] != ADDITIONAL_SCENARIO_EXPECTED_BLOCKED[name]
            )
            safety_runs.append(rec)

    return {
        "evidence_suite_version": EVIDENCE_SUITE_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "config": {
            "core_scenario_names": core_names,
            "additional_scenario_names": list(additional_scenario_names),
            "methods": list(methods),
            "fit_methods": list(fit_methods),
            "side": side,
            "data_seeds": [int(s) for s in data_seeds],
            "sim_seeds": [int(s) for s in sim_seeds],
            "n_simulations": int(n_sim),
            "alpha": float(alpha),
            "target_power": float(target_power),
        },
        "runs": runs,
        "safety_runs": safety_runs,
        "summary": summarise_v2(runs, safety_runs),
    }


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------


def _quantiles(values, qs=(0.1, 0.5, 0.9)):
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if not vals:
        return {f"p{int(q * 100)}": None for q in qs} | {"n": 0}
    arr = np.asarray(vals, dtype=float)
    out = {f"p{int(q * 100)}": float(np.quantile(arr, q)) for q in qs}
    out["n"] = int(len(arr))
    out["mean"] = float(np.mean(arr))
    return out


def summarise_v2(runs, safety_runs):
    """Compute every Stage-5 required statistic from the raw per-run records."""
    n_total = len(runs)
    completed = [r for r in runs if r.get("completed")]
    n_completed = len(completed)

    # Null calibration: |power_at_zero - alpha| over completed runs.
    alphas_by_run = [
        abs(r["power_at_zero"] - 0.05) for r in completed if r.get("power_at_zero") is not None
    ]

    # Power bias: power_at_reference - reference_power, over COMPLETED
    # (supported) runs only -- an incomplete/blocked run has no power bias.
    power_biases = [
        r["power_at_reference"] - r["reference_power"]
        for r in completed
        if r.get("power_at_reference") is not None and r.get("reference_power") is not None
    ]
    abs_power_biases = [abs(b) for b in power_biases]

    # MDE bias: relative to the reference MDE, only when BOTH the method and
    # the reference report a reached MDE (otherwise "bias" is not a single
    # number -- see false_mde_rate below for the reached/not-reached
    # disagreement itself).
    mde_biases_relative = []
    for r in completed:
        if (
            r.get("mde") is not None
            and r.get("mde_reached")
            and r.get("reference_mde") is not None
            and r.get("reference_mde_reached")
            and r["reference_mde"] != 0
        ):
            mde_biases_relative.append(abs(r["mde"] - r["reference_mde"]) / abs(r["reference_mde"]))

    # False-supported rate: a scenario the current method is EXPECTED to
    # block outright, but which reported completed=True.
    expected_block_runs = [r for r in runs if r["scenario"] in EXPECTED_BLOCKED_CORE_SCENARIOS]
    false_supported = [r for r in expected_block_runs if r.get("completed")]
    false_supported_rate = (
        len(false_supported) / len(expected_block_runs) if expected_block_runs else None
    )

    # False-MDE rate: the method reports a reached MDE while the reference
    # (known generative process) does NOT reach target power within bounds
    # -- the exact failure mode the persistence safety gate (Stage 3) exists
    # to prevent.
    mde_eligible = [r for r in completed if r.get("reference_mde_reached") is not None]
    false_mde = [
        r for r in mde_eligible if r.get("mde_reached") and not r.get("reference_mde_reached")
    ]
    false_mde_rate = len(false_mde) / len(mde_eligible) if mde_eligible else None

    n_blockers = sum(1 for r in runs if r.get("n_blockers", 0) > 0)
    n_fallback = sum(1 for r in runs if r.get("fallback_reason"))
    n_errored = sum(1 for r in runs if r.get("error"))

    # Seed sensitivity: for each (scenario, method, fit_method) combo, the
    # std of power_at_reference across every (data_seed, sim_seed) pair.
    by_combo = {}
    for r in completed:
        if r.get("power_at_reference") is None:
            continue
        key = (r["scenario"], r["method"], r["fit_method"])
        by_combo.setdefault(key, []).append(r["power_at_reference"])
    seed_sensitivities = [
        float(np.std(np.asarray(vs, dtype=float), ddof=1))
        for vs in by_combo.values()
        if len(vs) > 1
    ]

    runtimes = [r.get("runtime_s") for r in runs if r.get("runtime_s") is not None]

    # Worst-case bias among SUPPORTED scenarios specifically (excludes the
    # scenarios the safety policy is expected to block, since those never
    # report a completed power estimate in the first place).
    worst_case_bias = float(max(abs_power_biases)) if abs_power_biases else None

    safety_pass = sum(1 for r in safety_runs if r.get("safety_correct"))
    safety_total = len(safety_runs)

    return {
        "total_runs": n_total,
        "n_completed": n_completed,
        "n_errored": n_errored,
        "n_incomplete": n_total - n_completed - n_errored,
        "n_blocked": n_blockers,
        "n_fallback": n_fallback,
        "null_calibration": _quantiles(alphas_by_run),
        "power_bias": _quantiles(power_biases),
        "power_bias_abs": _quantiles(abs_power_biases),
        "power_bias_worst_case_supported": worst_case_bias,
        "mde_bias_relative": _quantiles(mde_biases_relative),
        "false_supported_rate": false_supported_rate,
        "false_supported_count": len(false_supported),
        "false_supported_denominator": len(expected_block_runs),
        "false_mde_rate": false_mde_rate,
        "false_mde_count": len(false_mde),
        "false_mde_denominator": len(mde_eligible),
        "blocker_rate": n_blockers / n_total if n_total else None,
        "fallback_rate": n_fallback / n_total if n_total else None,
        "seed_sensitivity_power_std": _quantiles(seed_sensitivities),
        "runtime_seconds": _quantiles(runtimes, qs=(0.5, 0.95)),
        "additional_safety_scenarios": {
            "n_scenarios": safety_total,
            "n_correct": safety_pass,
            "pass_rate": safety_pass / safety_total if safety_total else None,
            "results": [
                {
                    "scenario": r["scenario"],
                    "data_seed": r["data_seed"],
                    "expected_blocked": r["expected_blocked"],
                    "completed": r["completed"],
                    "safety_correct": r["safety_correct"],
                    "blockers": r.get("blockers", []),
                }
                for r in safety_runs
            ],
        },
    }


# ---------------------------------------------------------------------------
# Concise machine-readable summary (Stage 5, item: "Add a concise
# machine-readable summary"). Kept in a SEPARATE file from the byte-compared
# power-methodology-evidence.json, since it deliberately records the
# generating commit SHA -- which would otherwise make the byte-exact
# CI consistency check spuriously fail on every subsequent commit.
# ---------------------------------------------------------------------------


def _git_commit_sha():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=False
        )
        sha = out.stdout.strip()
        return sha if sha else "unknown"
    except Exception:
        return "unknown"


def build_evidence_v2_report(**run_kwargs):
    """Run the full v2 evidence suite and return the report dict (includes
    per-run records; ``write_summary`` below extracts the concise summary)."""
    return run_evidence_v2(**run_kwargs)


def build_concise_summary(report, generated_at=None):
    """The concise machine-readable summary: methodology version,
    scenario-suite version, code commit, simulation/replication settings,
    proposed thresholds, summary metrics, blocked scenarios, open decisions.
    """
    summary = report["summary"]
    blocked_scenarios = sorted(EXPECTED_BLOCKED_CORE_SCENARIOS) + [
        r["scenario"] for r in report["safety_runs"] if r["expected_blocked"]
    ]
    return {
        "methodology_version": report["methodology_version"],
        "scenario_suite_version": report["evidence_suite_version"],
        "code_commit": _git_commit_sha(),
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "simulation_settings": report["config"],
        "proposed_acceptance_thresholds": PROPOSED_ACCEPTANCE_THRESHOLDS,
        "summary_metrics": summary,
        "blocked_scenarios": sorted(set(blocked_scenarios)),
        "open_decisions": [
            "Primary power simulation method (model_simulation vs residual_simulation "
            "vs placebo_empirical) -- see ADR-001.",
            "Whether the false_mde_rate / power_bias_abs_worst_case proposed thresholds "
            "above are the right bars, or need scenario-weighted adjustment -- see ADR-013/014.",
            "Whether irrelevant_controls_market / nonlinear_counterfactual_market / "
            "structural_break_market warrant their own safety gates (currently reported "
            "as evidence only, never blocking) -- see ADR-005.",
            "Production simulation count and duration/market-share scenario grids "
            "(this suite uses a reduced n_sim for tractable CI runtime) -- see ADR-015/016.",
        ],
        "status": "For methodology approval -- this summary is decision evidence, not an "
        "approval record.",
    }
