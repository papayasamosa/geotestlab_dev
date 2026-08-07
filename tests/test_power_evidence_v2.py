"""Stage 5: power-methodology evidence v2 (geotestlab.power.evidence_v2) tests.

Covers the multi-seed evidence harness, the five additional safety
scenarios, the aggregate-statistics computation (bias quantiles, false
rates, seed sensitivity, runtime distribution), and the concise
machine-readable summary -- independent of the actual committed evidence
artifact (that is exercised end to end by the slow full-suite test).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from geotestlab.power.evidence_v2 import (
    ADDITIONAL_SAFETY_SCENARIOS,
    ADDITIONAL_SCENARIO_EXPECTED_BLOCKED,
    EVIDENCE_SUITE_VERSION,
    EXPECTED_BLOCKED_CORE_SCENARIOS,
    PROPOSED_ACCEPTANCE_THRESHOLDS,
    build_concise_summary,
    build_duplicate_keys_scenario,
    build_irrelevant_controls_scenario,
    build_nonlinear_counterfactual_scenario,
    build_structural_break_scenario,
    build_test_region_partial_missingness_scenario,
    build_v2_scenario,
    run_evidence_v2,
    summarise_v2,
)
from geotestlab.power.market_evidence import MarketScenario


# ---------------------------------------------------------------------------
# Additional safety-scenario builders
# ---------------------------------------------------------------------------
class TestAdditionalScenarioBuilders:
    def test_all_registered_scenarios_buildable(self):
        for name in ADDITIONAL_SAFETY_SCENARIOS:
            sc = build_v2_scenario(name, seed=0)
            assert isinstance(sc, MarketScenario)
            assert sc.name == name
            assert sc.pre_count >= 104  # headroom above the weekly history floor

    def test_test_region_partial_missingness_drops_only_t2_dates(self):
        sc = build_test_region_partial_missingness_scenario(seed=0)
        t1_dates = set(sc.df.loc[sc.df["region"] == "T1", "date"])
        t2_dates = set(sc.df.loc[sc.df["region"] == "T2", "date"])
        assert len(t1_dates) > len(t2_dates)

    def test_duplicate_keys_scenario_has_duplicates(self):
        sc = build_duplicate_keys_scenario(seed=0)
        dup_count = sc.df.duplicated(subset=["region", "date"]).sum()
        assert dup_count >= 5

    def test_irrelevant_controls_scenario_adds_junk_regions(self):
        sc = build_irrelevant_controls_scenario(seed=0)
        assert set(sc.control_regions) >= {"C1", "C2", "C3", "C4", "J1", "J2", "J3"}
        assert {"J1", "J2", "J3"} <= set(sc.df["region"].unique())

    def test_nonlinear_and_structural_break_scenarios_differ_from_base(self):
        base = build_test_region_partial_missingness_scenario(seed=0)  # unmodified T1
        nonlinear = build_nonlinear_counterfactual_scenario(seed=0)
        structural = build_structural_break_scenario(seed=0)
        base_t1 = base.df.loc[base.df["region"] == "T1"].sort_values("date")["kpi"].to_numpy()
        nl_t1 = (
            nonlinear.df.loc[nonlinear.df["region"] == "T1"].sort_values("date")["kpi"].to_numpy()
        )
        sb_t1 = (
            structural.df.loc[structural.df["region"] == "T1"].sort_values("date")["kpi"].to_numpy()
        )
        assert not np.allclose(base_t1, nl_t1)
        assert not np.allclose(base_t1, sb_t1)

    def test_expected_blocked_table_covers_every_scenario(self):
        assert set(ADDITIONAL_SCENARIO_EXPECTED_BLOCKED) == set(ADDITIONAL_SAFETY_SCENARIOS)

    def test_unknown_scenario_rejected(self):
        with pytest.raises(ValueError):
            build_v2_scenario("no_such_scenario")


# ---------------------------------------------------------------------------
# Multi-seed evidence run (small/fast configuration)
# ---------------------------------------------------------------------------
class TestRunEvidenceV2:
    def test_core_and_safety_runs_shape(self):
        report = run_evidence_v2(
            scenario_names=["weekly_104", "weekly_52"],
            methods=("model_simulation",),
            fit_methods=("ols",),
            data_seeds=(0, 1),
            sim_seeds=(0,),
            n_sim=100,
        )
        # 2 scenarios x 1 method x 1 fit x 2 data seeds x 1 sim seed = 4
        assert len(report["runs"]) == 4
        # 5 additional scenarios x 2 data seeds x 1 sim seed each = 10
        assert len(report["safety_runs"]) == 10
        assert report["evidence_suite_version"] == EVIDENCE_SUITE_VERSION
        for r in report["runs"]:
            assert "data_seed" in r
            assert "reference_mde" in r
            assert "reference_mde_reached" in r

    def test_data_seeds_produce_independent_scenario_data(self):
        report = run_evidence_v2(
            scenario_names=["weekly_104"],
            methods=("model_simulation",),
            fit_methods=("ols",),
            data_seeds=(0, 1),
            sim_seeds=(0,),
            n_sim=100,
        )
        runs = report["runs"]
        assert runs[0]["data_seed"] != runs[1]["data_seed"]
        # Different data seeds must not produce identical null_sd (a
        # different synthetic dataset, not just a different Monte Carlo draw).
        assert runs[0]["null_sd"] != runs[1]["null_sd"]

    def test_expected_blocked_core_scenarios_registered(self):
        assert EXPECTED_BLOCKED_CORE_SCENARIOS <= {
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
        }


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------
class TestSummariseV2:
    def _completed_run(
        self,
        scenario,
        power_ref,
        power_at_ref,
        mde=None,
        mde_reached=False,
        ref_mde=None,
        ref_mde_reached=False,
        runtime=0.1,
        blockers=None,
        fallback_reason=None,
    ):
        return {
            "scenario": scenario,
            "method": "model_simulation",
            "fit_method": "ols",
            "completed": True,
            "power_at_zero": 0.05,
            "power_at_reference": power_at_ref,
            "reference_power": power_ref,
            "mde": mde,
            "mde_reached": mde_reached,
            "reference_mde": ref_mde,
            "reference_mde_reached": ref_mde_reached,
            "runtime_s": runtime,
            "n_blockers": 0,
            "fallback_reason": fallback_reason,
            "error": None,
            "blockers": blockers or [],
        }

    def _blocked_run(self, scenario, runtime=0.05):
        return {
            "scenario": scenario,
            "method": "model_simulation",
            "fit_method": "ols",
            "completed": False,
            "power_at_zero": None,
            "power_at_reference": None,
            "reference_power": 0.5,
            "mde": None,
            "mde_reached": False,
            "reference_mde": 5.0,
            "reference_mde_reached": True,
            "runtime_s": runtime,
            "n_blockers": 1,
            "fallback_reason": None,
            "error": None,
            "blockers": ["some safety reason"],
        }

    def test_power_bias_and_quantiles(self):
        runs = [
            self._completed_run("weekly_104", power_ref=0.80, power_at_ref=0.82),
            self._completed_run("weekly_104", power_ref=0.80, power_at_ref=0.76),
        ]
        summary = summarise_v2(runs, [])
        assert summary["power_bias"]["n"] == 2
        assert summary["power_bias"]["mean"] == pytest.approx((0.02 + -0.04) / 2)
        assert summary["power_bias_abs"]["mean"] == pytest.approx((0.02 + 0.04) / 2)

    def test_false_supported_rate_uses_expected_blocked_scenarios(self):
        runs = [
            self._completed_run(
                "mde_not_reached", power_ref=0.5, power_at_ref=0.5
            ),  # false positive
            self._blocked_run("mde_not_reached"),  # correctly blocked
            self._completed_run(
                "weekly_104", power_ref=0.8, power_at_ref=0.8
            ),  # not in expected-block set
        ]
        summary = summarise_v2(runs, [])
        assert summary["false_supported_denominator"] == 2  # both mde_not_reached runs
        assert summary["false_supported_count"] == 1
        assert summary["false_supported_rate"] == pytest.approx(0.5)

    def test_false_mde_rate_flags_reached_when_reference_never_reaches(self):
        runs = [
            self._completed_run(
                "mde_not_reached",
                power_ref=0.5,
                power_at_ref=0.5,
                mde=5.0,
                mde_reached=True,
                ref_mde=None,
                ref_mde_reached=False,
            ),
            self._completed_run(
                "weekly_104",
                power_ref=0.8,
                power_at_ref=0.8,
                mde=2.0,
                mde_reached=True,
                ref_mde=2.1,
                ref_mde_reached=True,
            ),
        ]
        summary = summarise_v2(runs, [])
        assert summary["false_mde_count"] == 1
        assert summary["false_mde_rate"] == pytest.approx(0.5)

    def test_no_completed_runs_yields_none_not_crash(self):
        summary = summarise_v2([self._blocked_run("weekly_52")], [])
        assert summary["n_completed"] == 0
        assert summary["power_bias"]["n"] == 0
        assert summary["false_mde_rate"] is None or summary["false_mde_denominator"] == 0

    def test_seed_sensitivity_computed_per_combo(self):
        runs = [
            self._completed_run("weekly_104", power_ref=0.8, power_at_ref=0.80),
            self._completed_run("weekly_104", power_ref=0.8, power_at_ref=0.90),
            self._completed_run("weekly_104", power_ref=0.8, power_at_ref=0.70),
        ]
        summary = summarise_v2(runs, [])
        assert summary["seed_sensitivity_power_std"]["n"] == 1  # one (scenario, method, fit) combo
        assert summary["seed_sensitivity_power_std"]["mean"] == pytest.approx(
            float(np.std([0.80, 0.90, 0.70], ddof=1))
        )

    def test_runtime_distribution(self):
        runs = [self._completed_run("weekly_104", 0.8, 0.8, runtime=r) for r in (0.1, 0.2, 0.3)]
        summary = summarise_v2(runs, [])
        assert summary["runtime_seconds"]["n"] == 3
        assert summary["runtime_seconds"]["p50"] == pytest.approx(0.2)

    def test_blocker_and_fallback_rates(self):
        runs = [
            self._completed_run("weekly_104", 0.8, 0.8, fallback_reason="rank_deficient"),
            self._blocked_run("weekly_52"),
        ]
        summary = summarise_v2(runs, [])
        assert summary["fallback_rate"] == pytest.approx(0.5)
        assert summary["blocker_rate"] == pytest.approx(0.5)

    def test_safety_scenario_pass_rate(self):
        safety_runs = [
            {
                "scenario": "duplicate_keys",
                "data_seed": 0,
                "completed": False,
                "expected_blocked": True,
                "safety_correct": True,
                "blockers": ["x"],
            },
            {
                "scenario": "irrelevant_controls_market",
                "data_seed": 0,
                "completed": True,
                "expected_blocked": False,
                "safety_correct": True,
                "blockers": [],
            },
        ]
        summary = summarise_v2([], safety_runs)
        assert summary["additional_safety_scenarios"]["n_scenarios"] == 2
        assert summary["additional_safety_scenarios"]["pass_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Concise machine-readable summary
# ---------------------------------------------------------------------------
class TestConciseSummary:
    def test_summary_has_required_fields(self):
        report = run_evidence_v2(
            scenario_names=["weekly_104"],
            additional_scenario_names=("duplicate_keys",),
            methods=("model_simulation",),
            fit_methods=("ols",),
            data_seeds=(0,),
            sim_seeds=(0,),
            n_sim=100,
        )
        summary = build_concise_summary(report)
        for key in (
            "methodology_version",
            "scenario_suite_version",
            "code_commit",
            "generated_at",
            "simulation_settings",
            "proposed_acceptance_thresholds",
            "summary_metrics",
            "blocked_scenarios",
            "open_decisions",
            "status",
        ):
            assert key in summary, key
        assert summary["proposed_acceptance_thresholds"] == PROPOSED_ACCEPTANCE_THRESHOLDS
        assert isinstance(summary["code_commit"], str) and len(summary["code_commit"]) > 0
        assert "duplicate_keys" in summary["blocked_scenarios"]
        assert "for methodology approval" in summary["status"].lower()

    def test_thresholds_are_proposed_not_approved(self):
        # Structural guard: the thresholds dict must never be silently
        # renamed/relabelled to imply approval.
        assert "proposed" in "PROPOSED_ACCEPTANCE_THRESHOLDS".lower()
        assert set(PROPOSED_ACCEPTANCE_THRESHOLDS) == {
            "null_calibration_abs_error",
            "power_bias_abs_mean",
            "power_bias_abs_worst_case",
            "mde_bias_relative",
            "false_supported_rate",
            "false_mde_rate",
            "seed_sensitivity_power_std",
            "runtime_p95_seconds",
        }


# ---------------------------------------------------------------------------
# Committed evidence v2 artifacts (structural checks only -- this artifact is
# NOT byte-reproducible run to run because it records wall-clock runtime and
# a generation timestamp, so there is no CI consistency check for it, unlike
# the v1 report).
# ---------------------------------------------------------------------------
class TestCommittedEvidenceV2Artifacts:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    REPORT_PATH = REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2.json"
    SUMMARY_PATH = (
        REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2-summary.json"
    )

    def test_report_and_summary_exist_and_are_valid_json(self):
        assert self.REPORT_PATH.exists(), f"missing: {self.REPORT_PATH}"
        assert self.SUMMARY_PATH.exists(), f"missing: {self.SUMMARY_PATH}"
        report = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        summary = json.loads(self.SUMMARY_PATH.read_text(encoding="utf-8"))
        assert report["summary"]["total_runs"] > 0
        assert summary["summary_metrics"]["total_runs"] == report["summary"]["total_runs"]

    def test_report_covers_the_required_scenario_categories(self):
        report = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        core = set(report["config"]["core_scenario_names"])
        additional = set(report["config"]["additional_scenario_names"])
        # History lengths, daily seasonality, high/near-unit-root
        # persistence, heteroskedasticity, seasonal residuals, low-volume,
        # MDE-not-reached, exact-duplicate controls.
        assert {
            "weekly_52",
            "weekly_104",
            "weekly_156",
            "daily_weekday",
            "high_autocorrelation",
            "heteroskedastic",
            "seasonal_residuals",
            "low_volume",
            "mde_not_reached",
            "duplicate_controls",
        } <= core
        # Partial test missingness, duplicate region-date keys, irrelevant
        # controls, nonlinear/structural-break counterfactuals.
        assert {
            "test_region_partial_missingness",
            "duplicate_keys",
            "irrelevant_controls_market",
            "nonlinear_counterfactual_market",
            "structural_break_market",
        } <= additional

    def test_report_used_multiple_data_and_simulation_seeds(self):
        report = json.loads(self.REPORT_PATH.read_text(encoding="utf-8"))
        assert len(report["config"]["data_seeds"]) >= 2
        assert len(report["config"]["sim_seeds"]) >= 2

    def test_summary_records_a_real_commit_sha(self):
        summary = json.loads(self.SUMMARY_PATH.read_text(encoding="utf-8"))
        sha = summary["code_commit"]
        assert sha != "unknown"
        assert len(sha) == 40  # full git SHA-1 hex
