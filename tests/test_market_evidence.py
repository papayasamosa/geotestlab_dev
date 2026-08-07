"""Stage 4: power methodology — realistic market-shaped evidence tests.

Tests the market-evidence machinery in ``geotestlab.power.market_evidence``:

- scenario structure (weekly histories, daily weekday seasonality, tracking
  outages, low volume, high autocorrelation, heteroskedasticity, seasonal
  residuals, collinear / duplicate / many-weak controls, MDE-not-reached);
- the known generative reference (null SD vs the analytic AR(1) closed form,
  reference power vs the exact closed form, reference MDE, determinism);
- the evidence harness (null calibration, power calibration, MDE bias, seed
  sensitivity, fallback rates, runtime, failure modes, JSON-safety,
  determinism);
- report combine/write helpers.

The full evidence matrix is regenerated only by the ``@pytest.mark.slow`` test
(and ``scripts/update_market_evidence.py``), which compares against the
committed report in ``docs/spikes/evidence/``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from geotestlab.power import (
    MARKET_SCENARIOS,
    PowerConfig,
    analytic_power,
    analytic_total_variance,
    build_date_keyed_matrix,
    build_market_scenario,
    combine_evidence,
    fit_counterfactual,
    reference_mde,
    reference_null_sd,
    reference_power,
    run_market_evidence,
    run_power_analysis,
    strip_timing,
    write_evidence_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _small_evidence(
    scenarios=("weekly_104",),
    methods=("model_simulation",),
    fit_methods=("ols",),
    sides=("one_sided_positive",),
    seeds=(0,),
    n_sim=300,
):
    return run_market_evidence(
        scenario_names=list(scenarios),
        methods=methods,
        fit_methods=fit_methods,
        sides=sides,
        seeds=seeds,
        n_sim=n_sim,
    )


# ---------------------------------------------------------------------------
# Scenario structure
# ---------------------------------------------------------------------------
class TestScenarioStructure:
    def test_weekly_histories_have_correct_pre_counts(self):
        for name, pre in (("weekly_52", 52), ("weekly_104", 104), ("weekly_156", 156)):
            sc = build_market_scenario(name)
            assert sc.pre_count == pre
            assert sc.df["date"].nunique() == pre + 12
            assert sc.df["region"].nunique() == 6  # 2 test + 4 control

    def test_all_scenarios_are_registered(self):
        assert "weekly_52" in MARKET_SCENARIOS
        assert "mde_not_reached" in MARKET_SCENARIOS
        assert len(MARKET_SCENARIOS) >= 12

    def test_multiple_test_regions_aggregated_by_sum(self):
        sc = build_market_scenario("weekly_104")
        test, _, _ = build_date_keyed_matrix(sc.df, ("T1", "T2"), ("C1", "C2", "C3", "C4"))
        piv = sc.df.pivot_table(index="date", columns="region", values="kpi", aggfunc="first")
        manual = piv["T1"].fillna(0.0) + piv["T2"].fillna(0.0)
        manual.index = pd.to_datetime(manual.index)
        assert np.allclose(test.to_numpy(), manual.reindex(test.index).to_numpy())

    def test_daily_weekday_has_weekday_seasonality(self):
        sc = build_market_scenario("daily_weekday")
        piv = sc.df.pivot_table(index="date", columns="region", values="kpi")
        t1 = piv["T1"].dropna()
        wd_mean = t1.groupby(t1.index.weekday).mean()
        assert wd_mean.max() - wd_mean.min() > 5.0  # material weekday spread

    def test_daily_weekday_tracking_outage_reported(self):
        sc = build_market_scenario("daily_weekday")
        test, _, diag = build_date_keyed_matrix(sc.df, sc.test_regions, sc.control_regions)
        assert diag["dates_expected"] == 52 * 7 + 14
        assert diag["dates_removed"] >= 6
        # Outages are PRE-period: the test window (last 14 dates) is clean,
        # while the pre-period carries the missing values.
        assert test.iloc[-14:].notna().all()
        assert test.iloc[:-14].isna().any()

    def test_low_volume_uses_absolute_injection(self):
        sc = build_market_scenario("low_volume")
        assert sc.truth["injection"] == "absolute"
        assert sc.truth["cf_sum_test"] < 1000.0

    def test_high_autocorrelation_truth(self):
        assert build_market_scenario("high_autocorrelation").truth["rho"] == 0.9

    def test_heteroskedastic_noise_scales_with_level(self):
        sc = build_market_scenario("heteroskedastic")
        cf_test = sc.truth["cf"][sc.pre_count :]
        sigt = sc.truth["sigma_agg_test"]
        hi = np.mean(sigt[cf_test > np.median(cf_test)])
        lo = np.mean(sigt[cf_test <= np.median(cf_test)])
        assert hi > lo * 1.1

    def test_seasonal_residuals_weekend_noisier(self):
        sc = build_market_scenario("seasonal_residuals")
        dates = sorted(pd.to_datetime(pd.Series(sc.df["date"].unique())))[sc.pre_count :]
        wd = np.array([d.weekday() for d in dates])
        sigt = sc.truth["sigma_agg_test"]
        assert np.mean(sigt[wd >= 5]) > np.mean(sigt[wd < 5]) * 1.5

    def test_collinear_controls_ill_conditioned_full_rank(self):
        sc = build_market_scenario("collinear_controls")
        dates = sorted(pd.to_datetime(pd.Series(sc.df["date"].unique())))
        pre_df = sc.df[sc.df["date"].isin(set(dates[: sc.pre_count]))]
        fit = fit_counterfactual(pre_df, sc.test_regions, sc.control_regions, fit_method="ols")
        assert fit.fit_status == "ok"
        assert fit.diagnostics["condition_number"] is not None
        assert fit.diagnostics["condition_number"] > 1e3

    def test_duplicate_controls_sanitised_and_fitted(self):
        # The exact-duplicate control (C2 == C1) is sanitised away BEFORE the
        # rank/condition check, so the fit proceeds on the remaining
        # informative controls instead of falling back to a constant mean.
        sc = build_market_scenario("duplicate_controls")
        dates = sorted(pd.to_datetime(pd.Series(sc.df["date"].unique())))
        pre_df = sc.df[sc.df["date"].isin(set(dates[: sc.pre_count]))]
        fit = fit_counterfactual(pre_df, sc.test_regions, sc.control_regions, fit_method="ols")
        assert fit.fit_status == "ok"
        assert fit.diagnostics["fallback_reason"] is None
        assert {"region": "C2", "reason": "duplicate_of:C1"} in fit.diagnostics["removed_controls"]
        assert "C2" not in fit.diagnostics["retained_control_regions"]
        assert "C1" in fit.diagnostics["retained_control_regions"]

    def test_mde_not_reached_reference_unreached(self):
        sc = build_market_scenario("mde_not_reached")
        mde, reached = reference_mde(sc)
        assert reached is False
        assert mde is None

    def test_unknown_scenario_rejected(self):
        with pytest.raises(ValueError):
            build_market_scenario("no_such_scenario")


# ---------------------------------------------------------------------------
# Known generative reference
# ---------------------------------------------------------------------------
class TestReferenceTruth:
    def test_reference_null_sd_matches_analytic(self):
        sc = build_market_scenario("weekly_104")
        sd = reference_null_sd(sc)
        # Two test regions, each innovation sd 2.0 -> aggregate sigma 2*sqrt(2).
        analytic_sd = np.sqrt(
            analytic_total_variance(sc.truth["rho"], 2.0 * np.sqrt(2.0), sc.truth["n_test"])
        )
        assert sd == pytest.approx(analytic_sd, rel=0.02)

    def test_reference_power_matches_analytic(self):
        sc = build_market_scenario("weekly_104")
        sd = reference_null_sd(sc)
        cf = sc.truth["cf_sum_test"]
        e = sc.truth["reference_effect"]
        expected = analytic_power(cf, sd, cf * e / 100.0, 0.05, "one_sided_positive")
        assert reference_power(sc, e) == pytest.approx(expected, rel=1e-6)

    def test_reference_null_calibration(self):
        sc = build_market_scenario("weekly_104")
        assert reference_power(sc, 0.0) == pytest.approx(0.05, abs=0.01)

    def test_reference_mde_hits_target_power(self):
        sc = build_market_scenario("weekly_104")
        mde, reached = reference_mde(sc, target_power=0.80)
        assert reached
        assert mde is not None
        assert reference_power(sc, mde) >= 0.80 - 0.02

    def test_reference_deterministic(self):
        sc = build_market_scenario("weekly_104")
        assert reference_power(sc, 0.8) == reference_power(sc, 0.8)
        assert reference_null_sd(sc) == reference_null_sd(sc)

    def test_absolute_reference_scales_by_test_length(self):
        # Regression (Codex P1): the production spike's _shift treats an
        # absolute effect as a PER-PERIOD lift (total shift = effect * n_test);
        # the reference must use the same convention or low_volume power is
        # systematically wrong (was shift = effect, one period only).
        sc = build_market_scenario("low_volume")
        n_test = int(sc.truth["n_test"])
        sd = reference_null_sd(sc)
        e = 0.5
        expected = analytic_power(
            sc.truth["cf_sum_test"], sd, e * n_test, 0.05, "one_sided_positive"
        )
        assert reference_power(sc, e) == pytest.approx(expected, rel=1e-6)
        wrong = analytic_power(sc.truth["cf_sum_test"], sd, e, 0.05, "one_sided_positive")
        assert abs(reference_power(sc, e) - wrong) > 1e-3


class TestNoiseSimulator:
    def test_shape_and_reproducible(self):
        from geotestlab.power.market_evidence import noise_sum_simulator

        sc = build_market_scenario("weekly_104")
        sim = noise_sum_simulator(
            np.asarray(sc.truth["sigma_agg_test"], dtype=float),
            float(sc.truth["rho"]),
            int(sc.truth["n_test"]),
        )
        a = sim(50, np.random.default_rng(1))
        b = sim(50, np.random.default_rng(1))
        assert len(a) == 50
        assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Evidence harness
# ---------------------------------------------------------------------------
class TestMethodologySafetyExpectedStates:
    """Stage 3: the expected support state per market scenario, in one place
    for direct traceability to the sequential-plan acceptance table."""

    EXPECTED_BLOCKED = {
        "weekly_52",
        "daily_weekday",
        "seasonal_residuals",  # daily frequency -> blocked, same as daily_weekday
        "heteroskedastic",
        "mde_not_reached",
    }
    EXPECTED_SUPPORTED = {
        "weekly_104",
        "weekly_156",
        "low_volume",
        "high_autocorrelation",
        "collinear_controls",
        "many_weak_controls",
        "duplicate_controls",
    }

    def test_expected_states_at_evidence_seeds(self):
        from geotestlab.power.market_evidence import _evidence_grid, _run_one

        assert self.EXPECTED_BLOCKED | self.EXPECTED_SUPPORTED == set(MARKET_SCENARIOS)
        for name in MARKET_SCENARIOS:
            sc = build_market_scenario(name)
            grid = _evidence_grid(sc.truth["mde_bounds"])
            for seed in (0, 1):
                rec = _run_one(
                    sc, "model_simulation", "ols", "one_sided_positive", seed, 300, grid, 0.05, 0.80
                )
                if name in self.EXPECTED_BLOCKED:
                    assert rec["completed"] is False, f"{name} seed={seed} expected blocked"
                    assert rec["n_blockers"] >= 1
                else:
                    assert rec["completed"] is True, f"{name} seed={seed} expected supported"

    def test_duplicate_controls_sanitised_and_fitted(self):
        from geotestlab.power.market_evidence import _evidence_grid, _run_one

        sc = build_market_scenario("duplicate_controls")
        grid = _evidence_grid(sc.truth["mde_bounds"])
        rec = _run_one(
            sc, "model_simulation", "ols", "one_sided_positive", 0, 300, grid, 0.05, 0.80
        )
        assert rec["completed"] is True
        assert rec["fit_status"] == "ok"
        assert rec["fallback_reason"] is None


class TestMarketEvidenceHarness:
    def test_runs_all_requested_cells(self):
        ev = run_market_evidence(
            scenario_names=["weekly_104", "mde_not_reached"],
            methods=["model_simulation", "placebo_empirical"],
            fit_methods=["ols"],
            seeds=(0,),
            n_sim=200,
        )
        assert len(ev["runs"]) == 2 * 2 * 1 * 1 * 1
        assert ev["totals"]["total_runs"] == 4

    def test_placebo_recorded_once_with_na_fit_method(self):
        # Regression (Codex P2): placebo_empirical never receives a fit method,
        # so it must be recorded ONCE under ``n/a``, not once per fit method.
        ev = run_market_evidence(
            scenario_names=["weekly_104"],
            methods=["model_simulation", "placebo_empirical"],
            fit_methods=["ols", "elastic_net", "lasso"],
            seeds=(0,),
            n_sim=200,
        )
        model = [r for r in ev["runs"] if r["method"] == "model_simulation"]
        placebo = [r for r in ev["runs"] if r["method"] == "placebo_empirical"]
        assert len(model) == 3  # one per fit method
        assert len(placebo) == 1  # once, no fit-method labelling
        assert placebo[0]["fit_method"] == "n/a"
        cells = ev["summaries"]["weekly_104"]["cells"]
        assert "placebo_empirical|n/a" in cells
        assert "placebo_empirical|ols" not in cells

    def test_json_safe(self):
        ev = _small_evidence(seeds=(0, 1))
        json.dumps(ev)

    def test_deterministic(self):
        a = _small_evidence(seeds=(0, 1))
        b = _small_evidence(seeds=(0, 1))
        assert strip_timing(a) == strip_timing(b)

    def test_timing_recorded_but_strippable(self):
        ev = _small_evidence(seeds=(0, 1))
        assert all(r["runtime_s"] > 0.0 for r in ev["runs"])
        assert ev["totals"]["total_runtime_s"] > 0.0
        stripped = strip_timing(ev)
        assert all("runtime_s" not in r for r in stripped["runs"])
        assert "total_runtime_s" not in stripped["totals"]
        json.dumps(stripped)

    def test_strip_timing_handles_combined_parts(self):
        # combine_evidence keeps per-part totals; strip_timing must strip the
        # runtime from every part so a combined report is byte-reproducible.
        e1 = _small_evidence(seeds=(0,), n_sim=200)
        e2 = run_market_evidence(
            scenario_names=["weekly_104"],
            methods=["model_simulation"],
            fit_methods=["ols"],
            sides=("two_sided",),
            seeds=(0,),
            n_sim=200,
        )
        combined = strip_timing(combine_evidence(e1, e2))
        assert all("runtime_s" not in r for r in combined["runs"])
        assert "total_runtime_s" not in combined["totals"]
        for part in combined["parts"]:
            assert "total_runtime_s" not in part["totals"]
        json.dumps(combined)

    def test_model_simulation_null_calibration(self):
        ev = _small_evidence(seeds=(0, 1))
        for r in ev["runs"]:
            assert abs(r["power_at_zero"] - 0.05) < 0.04

    def test_model_simulation_power_calibration(self):
        ev = _small_evidence(seeds=(0, 1))
        for r in ev["runs"]:
            assert abs(r["power_at_reference"] - r["reference_power"]) < 0.08

    def test_model_simulation_mde_bias(self):
        ev = _small_evidence(seeds=(0, 1))
        for r in ev["runs"]:
            assert r["mde_reached"] is True
            assert r["mde"] is not None
        sc = build_market_scenario("weekly_104")
        ref_mde, _ = reference_mde(sc)
        for r in ev["runs"]:
            assert abs(r["mde"] - ref_mde) < 0.75

    def test_placebo_null_calibration_inflated_with_few_windows(self):
        # 8 placebo windows -> the empirical threshold is near the max, so the
        # measured false-positive rate is well above alpha (documented finding).
        ev = _small_evidence(methods=("placebo_empirical",), seeds=(0, 1))
        for r in ev["runs"]:
            assert r["completed"] is True
            assert r["windows_available"] < 10
            assert r["power_at_zero"] > 0.09

    def test_weekly_52_placebo_incomplete(self):
        ev = run_market_evidence(
            scenario_names=["weekly_52"],
            methods=["placebo_empirical"],
            fit_methods=["ols"],
            seeds=(0,),
            n_sim=200,
        )
        r = ev["runs"][0]
        assert r["completed"] is False
        assert r["windows_available"] < 5
        assert r["mde"] is None
        assert r["n_errors"] >= 1
        assert r["n_blockers"] >= 1

    def test_mde_not_reached_result(self):
        # The TRUE generative process never reaches target power within
        # bounds. Before Stage 3, the fitted AR(1) under near-unit-root
        # autocorrelation underestimated persistence (rho_hat ~0.90 vs truth
        # 0.99) and the null width, so the METHOD used to falsely report a
        # reachable MDE -- exactly the false-MDE failure mode the
        # persistence-uncertainty safety gate exists to catch. The fitted
        # rho's own estimation uncertainty puts a plausible near-unit-root
        # process well within reach, so this must now BLOCK rather than
        # report a misleadingly well-formed (but false) MDE.
        ev = run_market_evidence(
            scenario_names=["mde_not_reached"],
            methods=["model_simulation"],
            fit_methods=["ols"],
            seeds=(0, 1),
            n_sim=300,
        )
        sc = build_market_scenario("mde_not_reached")
        _, ref_reached = reference_mde(sc)
        assert ref_reached is False
        for r in ev["runs"]:
            assert r["completed"] is False
            assert r["mde"] is None
            assert r["mde_reached"] is False
            assert r["n_blockers"] >= 1

    def test_duplicate_controls_sanitised_not_fallback_recorded(self):
        ev = run_market_evidence(
            scenario_names=["duplicate_controls"],
            methods=["model_simulation"],
            fit_methods=["ols", "elastic_net", "lasso"],
            seeds=(0,),
            n_sim=200,
        )
        for r in ev["runs"]:
            assert r["fallback_reason"] is None
            assert r["fit_status"] == "ok"

    def test_low_volume_placebo_error_recorded(self):
        # Placebo-empirical supports relative injection only -> NotImplementedError
        # is surfaced as a failure mode, never swallowed.
        ev = run_market_evidence(
            scenario_names=["low_volume"],
            methods=["placebo_empirical"],
            fit_methods=["ols"],
            seeds=(0,),
            n_sim=200,
        )
        r = ev["runs"][0]
        assert r["error"] is not None
        assert "relative injection only" in r["error"]

    def test_seed_sensitivity_recorded(self):
        ev = _small_evidence(seeds=(0, 1))
        cell = ev["summaries"]["weekly_104"]["cells"]["model_simulation|ols"]
        assert cell["power_at_reference_std"] is not None
        assert cell["power_at_reference_std"] >= 0.0
        assert cell["mde_std"] is not None

    def test_runtime_recorded(self):
        ev = _small_evidence(seeds=(0, 1))
        assert all(r["runtime_s"] > 0.0 for r in ev["runs"])
        assert ev["totals"]["total_runtime_s"] > 0.0

    def test_history_sensitivity_rho_estimation(self):
        ev = run_market_evidence(
            scenario_names=["weekly_52", "weekly_104", "weekly_156"],
            methods=["model_simulation"],
            fit_methods=["ols"],
            seeds=(0, 1),
            n_sim=300,
        )
        # 104/156-week histories estimate rho within a wide band of the truth
        # (0.4) and remain "supported" under the Stage-3 weekly history
        # floor (104 retained periods).
        for name in ("weekly_104", "weekly_156"):
            cell = ev["summaries"][name]["cells"]["model_simulation|ols"]
            assert abs(cell["rho_hat_mean"] - 0.4) < 0.2
        # 52 weekly periods is below the history floor -- the evidence that
        # motivated the floor (+0.306 power bias below 104 periods for the
        # current method) -- and is now BLOCKED outright rather than
        # producing a (biased) completed rho estimate.
        for r in ev["runs"]:
            if r["scenario"] == "weekly_52":
                assert r["completed"] is False
                assert r["n_blockers"] >= 1

    def test_side_matrix_reported(self):
        ev = run_market_evidence(
            scenario_names=["weekly_104"],
            methods=["model_simulation"],
            fit_methods=["ols"],
            sides=("one_sided_negative", "two_sided"),
            seeds=(0,),
            n_sim=300,
        )
        by_side = ev["summaries"]["weekly_104"]["by_side"]
        assert "one_sided_negative|model_simulation" in by_side
        assert "two_sided|model_simulation" in by_side
        neg = by_side["one_sided_negative|model_simulation"]
        two = by_side["two_sided|model_simulation"]
        assert neg["power_at_reference_mean"] is not None
        assert two["power_at_reference_mean"] is not None

    def test_effect_grid_resolves_small_effects(self):
        # The default uniform 200-point grid is unchanged.
        case = build_market_scenario("weekly_104")
        config = PowerConfig(
            method="model_simulation",
            n_simulations=300,
            random_seed=7,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
        )
        res = run_power_analysis(case.df, case.pre_count, config)
        assert len(res.effect_grid) == 200
        # The evidence grid is dense near zero and includes the bounds.
        from geotestlab.power.market_evidence import _evidence_grid

        grid = _evidence_grid(case.truth["mde_bounds"])
        assert grid[0] == 0.0
        assert grid[-1] == 50.0
        assert grid[1] < 0.1  # sub-0.1% resolution near zero
        config2 = PowerConfig(
            method="model_simulation",
            n_simulations=300,
            random_seed=7,
            test_regions=("T1", "T2"),
            control_regions=("C1", "C2", "C3", "C4"),
            effect_grid=grid,
        )
        res2 = run_power_analysis(case.df, case.pre_count, config2)
        assert len(res2.effect_grid) == len(grid)
        assert res2.effect_grid[0] == 0.0

    def test_bad_effect_grid_rejected(self):
        case = build_market_scenario("weekly_104")

        def _config(**over):
            kw = dict(
                method="model_simulation",
                n_simulations=100,
                random_seed=7,
                test_regions=("T1", "T2"),
                control_regions=("C1", "C2", "C3", "C4"),
            )
            kw.update(over)
            return PowerConfig(**kw)

        with pytest.raises(ValueError):  # < 2 points
            run_power_analysis(case.df, case.pre_count, _config(effect_grid=(0.0,)))
        with pytest.raises(ValueError):  # non-finite
            run_power_analysis(
                case.df, case.pre_count, _config(effect_grid=(0.0, float("nan"), 50.0))
            )
        with pytest.raises(ValueError):  # outside bounds
            run_power_analysis(case.df, case.pre_count, _config(effect_grid=(0.0, 60.0)))


# ---------------------------------------------------------------------------
# Combine / write helpers
# ---------------------------------------------------------------------------
class TestCombineAndWriteReport:
    def test_combine_evidence_merges_runs(self):
        e1 = _small_evidence(seeds=(0,), n_sim=200)
        e2 = run_market_evidence(
            scenario_names=["weekly_104"],
            methods=["model_simulation"],
            fit_methods=["ols"],
            sides=("two_sided",),
            seeds=(0,),
            n_sim=200,
        )
        combined = combine_evidence(e1, e2)
        assert len(combined["runs"]) == len(e1["runs"]) + len(e2["runs"])
        assert combined["totals"]["total_runs"] == 2
        assert "two_sided|model_simulation" in combined["summaries"]["weekly_104"]["by_side"]
        json.dumps(combined)

    def test_write_evidence_report_roundtrip(self, tmp_path):
        ev = _small_evidence(seeds=(0,), n_sim=200)
        path = tmp_path / "evidence.json"
        write_evidence_report(str(path), ev)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["totals"] == ev["totals"]
        assert loaded["config"] == ev["config"]


# ---------------------------------------------------------------------------
# Full committed report (slow)
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_full_evidence_report_matches_committed():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from update_market_evidence import REPORT_PATH, generate_full_report

    report = generate_full_report()
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    assert REPORT_PATH.exists(), (
        f"evidence report missing: {REPORT_PATH} "
        "(run: python scripts/update_market_evidence.py --approve)"
    )
    assert REPORT_PATH.read_text(encoding="utf-8") == payload

    # Sanity bounds on the committed evidence.
    totals = report["totals"]
    # Broad: 12 scenarios x (model 3 fits + residual 3 fits + placebo 1) x 1
    # side x 2 seeds = 168. Side matrix: weekly_104 x (1+1+1) x 2 sides x 2
    # seeds = 12. Total = 180.
    assert totals["total_runs"] == 168 + 12
    assert totals["n_errored"] == 2  # placebo x absolute-injection (low_volume), 2 seeds
    # Stage 3: duplicate/constant controls are sanitised BEFORE the rank
    # check, so duplicate_controls no longer falls back to a constant mean
    # (was >= 12 before the fix; the methodology-safety fallback rate is now
    # driven only by genuinely non-sanitisable rank deficiency, which none
    # of the current scenarios trigger).
    assert totals["n_fallback"] == 0
    # Stage 3: the methodology safety policy now blocks weekly_52 (history
    # floor), daily_weekday/seasonal_residuals (daily frequency/seasonality),
    # heteroskedastic (material heteroskedasticity) and mde_not_reached
    # (near-unit-root persistence) across every method/fit-method/seed cell
    # that reaches a fit, in addition to the pre-existing weekly_52 placebo
    # minimum-window incompleteness -- a large, deliberate increase from the
    # pre-Stage-3 count of 2.
    assert totals["n_incomplete"] >= 60
    sc104 = report["summaries"]["weekly_104"]
    model_ols = sc104["cells"]["model_simulation|ols"]
    assert abs(model_ols["null_calibration_mean"] - 0.05) < 0.04
    assert abs(model_ols["power_bias_vs_reference"]) < 0.08
    assert report["scenarios"][0]["name"] == "weekly_52"
