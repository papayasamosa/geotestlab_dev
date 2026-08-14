"""Stage 3: methodology safety policy (geotestlab.power.safety) unit tests.

Covers each safety dimension's supported / supported_with_warning /
unsupported / blocked branches directly, plus the combined
``evaluate_safety`` verdict (overall_status = most severe sub-status,
fallback fits skip persistence/heteroskedasticity), independent of any
particular market scenario.
"""

from __future__ import annotations

import numpy as np
import pytest

from geotestlab.power.safety import (
    BLOCKED,
    SUPPORTED,
    SUPPORTED_WITH_WARNING,
    UNSUPPORTED,
    MethodologySafetyPolicy,
    control_matrix_support,
    evaluate_safety,
    frequency_support,
    heteroskedasticity_support,
    history_support,
    persistence_support,
    seasonality_support,
)

POLICY = MethodologySafetyPolicy()


class TestFrequencySupport:
    def test_weekly_supported(self):
        status, reasons, _ = frequency_support("weekly", POLICY)
        assert status == SUPPORTED
        assert reasons == []

    def test_daily_blocked(self):
        status, reasons, _ = frequency_support("daily", POLICY)
        assert status == BLOCKED
        assert reasons

    def test_unknown_frequency_unsupported(self):
        status, reasons, _ = frequency_support("monthly", POLICY)
        assert status == UNSUPPORTED
        assert reasons


class TestSeasonalitySupport:
    def test_weekly_supported(self):
        status, reasons, _ = seasonality_support("weekly", POLICY)
        assert status == SUPPORTED
        assert reasons == []

    def test_daily_blocked(self):
        status, reasons, _ = seasonality_support("daily", POLICY)
        assert status == BLOCKED
        assert reasons


class TestHistorySupport:
    def test_below_floor_blocked(self):
        status, reasons, metrics = history_support(52, "weekly", "contiguous", 3, POLICY)
        assert status == BLOCKED
        assert "52" in reasons[0]
        assert metrics["min_periods"] == 104

    def test_at_floor_supported(self):
        status, reasons, _ = history_support(104, "weekly", "contiguous", 3, POLICY)
        assert status == SUPPORTED
        assert reasons == []

    def test_above_floor_non_contiguous_warns(self):
        status, reasons, _ = history_support(120, "weekly", "2 gap(s)", 3, POLICY)
        assert status == SUPPORTED_WITH_WARNING
        assert any("continuity" in r for r in reasons)

    def test_low_periods_per_predictor_warns(self):
        # 104 periods for 20 predictors is well below the 10x rule of thumb.
        status, reasons, _ = history_support(104, "weekly", "contiguous", 20, POLICY)
        assert status == SUPPORTED_WITH_WARNING
        assert any("predictor" in r for r in reasons)

    def test_unconfigured_frequency_unsupported(self):
        status, reasons, _ = history_support(200, "daily", "contiguous", 3, POLICY)
        assert status == UNSUPPORTED
        assert reasons


class TestPersistenceSupport:
    def test_low_rho_supported(self):
        status, reasons, metrics = persistence_support(0.3, 104, POLICY)
        assert status == SUPPORTED
        assert reasons == []
        assert metrics["rho"] == pytest.approx(0.3)

    def test_elevated_rho_warns(self):
        status, reasons, _ = persistence_support(0.85, 500, POLICY)
        assert status == SUPPORTED_WITH_WARNING
        assert reasons

    def test_near_unit_root_upper_bound_blocks(self):
        # Point estimate need not itself exceed the near-unit-root threshold
        # -- an elevated upper confidence bound is enough to block.
        status, reasons, metrics = persistence_support(0.9, 104, POLICY)
        assert status == BLOCKED
        assert metrics["rho_upper"] >= POLICY.persistence_near_unit_root_upper
        assert reasons

    def test_high_rho_more_periods_not_blocked(self):
        # The same point estimate with a MUCH larger sample (tighter
        # uncertainty) need not cross the near-unit-root upper bound.
        status, _reasons, metrics = persistence_support(0.85, 5000, POLICY)
        assert metrics["rho_upper"] < POLICY.persistence_near_unit_root_upper
        assert status in (SUPPORTED, SUPPORTED_WITH_WARNING)

    def test_insufficient_periods_unsupported(self):
        status, reasons, _ = persistence_support(0.5, 1, POLICY)
        assert status == UNSUPPORTED
        assert reasons


class TestHeteroskedasticitySupport:
    def test_stable_variance_supported(self):
        rng = np.random.default_rng(0)
        residuals = rng.normal(0.0, 1.0, 200)
        level = np.linspace(0.0, 100.0, 200)
        status, reasons, metrics = heteroskedasticity_support(residuals, level, POLICY)
        assert status == SUPPORTED
        assert reasons == []
        assert np.isfinite(metrics["variance_ratio_high_over_low_level"])
        assert "candidate_diagnostics" in metrics
        assert "scale_association_block_permutation_pvalue" in metrics

    def test_material_heteroskedasticity_blocks(self):
        rng = np.random.default_rng(0)
        level = np.linspace(0.0, 100.0, 200)
        # Innovation sd scales sharply with level -> a large low/high split ratio.
        residuals = rng.normal(0.0, 1.0 + level / 5.0, 200)
        status, reasons, metrics = heteroskedasticity_support(residuals, level, POLICY)
        assert status == BLOCKED
        assert reasons
        ratio = metrics["variance_ratio_high_over_low_level"]
        assert ratio >= POLICY.heteroskedasticity_ratio_block or ratio <= (
            1.0 / POLICY.heteroskedasticity_ratio_block
        )

    def test_too_few_residuals_unsupported(self):
        status, reasons, _ = heteroskedasticity_support([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], POLICY)
        assert status == UNSUPPORTED
        assert reasons

    def test_scale_association_candidate_is_seed_deterministic(self):
        rng = np.random.default_rng(11)
        level = np.linspace(10.0, 100.0, 120)
        residuals = rng.normal(0.0, 1.0 + level / 30.0, 120)
        first = heteroskedasticity_support(residuals, level, POLICY)
        second = heteroskedasticity_support(residuals, level, POLICY)
        assert first == second
        assert first[2]["scale_association_block_length"] == POLICY.heteroskedasticity_block_length

    def test_large_negative_levels_keep_permutation_seed_valid(self):
        rng = np.random.default_rng(12)
        residuals = rng.normal(0.0, 1.0, 120)
        level = np.full(120, -1_000_000_000.0)
        first = heteroskedasticity_support(residuals, level, POLICY)
        second = heteroskedasticity_support(residuals, level, POLICY)
        assert first == second
        assert first[0] in (SUPPORTED, BLOCKED)


class TestControlMatrixSupport:
    def test_ok_fit_no_removals_supported(self):
        status, reasons, _ = control_matrix_support(
            {"fallback_used": False, "removed_controls": []}
        )
        assert status == SUPPORTED
        assert reasons == []

    def test_sanitised_controls_warns_not_blocks(self):
        status, reasons, _ = control_matrix_support(
            {
                "fallback_used": False,
                "removed_controls": [{"region": "C2", "reason": "duplicate_of:C1"}],
            }
        )
        assert status == SUPPORTED_WITH_WARNING
        assert any("C2" in r for r in reasons)

    def test_fallback_warns_not_blocks(self):
        # A constant-mean fallback is an accepted, already-reported degraded
        # mode (see fit_counterfactual) -- NOT re-blocked by the safety
        # policy, only flagged.
        status, reasons, _ = control_matrix_support(
            {"fallback_used": True, "fallback_reason": "rank_deficient"}
        )
        assert status == SUPPORTED_WITH_WARNING
        assert any("rank_deficient" in r for r in reasons)


class TestEvaluateSafety:
    def _kwargs(self, **overrides):
        rng = np.random.default_rng(0)
        base = dict(
            frequency="weekly",
            retained_periods=120,
            continuity="contiguous",
            n_predictors=3,
            rho=0.3,
            fit_diagnostics={"fallback_used": False, "removed_controls": []},
            residuals=rng.normal(0.0, 1.0, 120),
            level=np.linspace(0.0, 100.0, 120),
        )
        base.update(overrides)
        return base

    def test_clean_case_supported(self):
        result = evaluate_safety(**self._kwargs())
        assert result["overall_status"] == SUPPORTED
        assert result["reasons"] == []
        assert result["policy_version"] == MethodologySafetyPolicy().version

    def test_one_blocking_dimension_blocks_overall(self):
        result = evaluate_safety(**self._kwargs(frequency="daily", retained_periods=400))
        assert result["overall_status"] == BLOCKED
        assert result["frequency_status"] == BLOCKED
        # Every category still reports its own status/reasons regardless.
        assert "history_status" in result
        assert "persistence_status" in result

    def test_fallback_skips_persistence_and_heteroskedasticity(self):
        # A near-unit-root rho would normally block, but on a fallback fit
        # persistence/heteroskedasticity are not meaningful diagnostics of
        # the (nonexistent) counterfactual dynamics and are not evaluated.
        result = evaluate_safety(
            **self._kwargs(
                rho=0.99,
                fit_diagnostics={"fallback_used": True, "fallback_reason": "rank_deficient"},
            )
        )
        assert result["persistence_status"] == SUPPORTED
        assert result["heteroskedasticity_status"] == SUPPORTED
        # But the fallback itself is still reported as a warning.
        assert result["control_matrix_status"] == SUPPORTED_WITH_WARNING
        assert result["overall_status"] == SUPPORTED_WITH_WARNING

    def test_multiple_warnings_overall_is_worst_warning(self):
        result = evaluate_safety(
            **self._kwargs(
                continuity="2 gap(s)",
                fit_diagnostics={
                    "fallback_used": False,
                    "removed_controls": [{"region": "C2", "reason": "constant"}],
                },
            )
        )
        assert result["history_status"] == SUPPORTED_WITH_WARNING
        assert result["control_matrix_status"] == SUPPORTED_WITH_WARNING
        assert result["overall_status"] == SUPPORTED_WITH_WARNING
        assert len(result["reasons"]) >= 2
