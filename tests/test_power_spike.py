"""Stage 5: power-analysis methodology spike — controlled synthetic-case tests.

Validates the corrected prototype on synthetic cases with KNOWN counterfactual
and AR(1) noise, where the true null distribution and power are analytic:

- generator truth (counterfactual sum, total variance, effect injection);
- model-based simulation matches the analytic power (method alignment);
- null calibration (power at effect=0 ~= alpha);
- negative-effect MDE (direction from side, non-negative magnitude);
- detection-criterion gating (only implemented criteria, never unapplied);
- effect-shape gating (step only in the service);
- independent calibration / alternative / diagnostics streams;
- rank-deficiency handling (explicit fallback with recorded reason);
- empty placebo evidence (explicit incomplete result, no MDE);
- date-keyed alignment (missing, duplicated, shuffled dates);
- explicit selected design (test/control regions, planned test dates);
- fit-method comparison evidence (OLS vs Elastic Net vs LASSO);
- structured result contract (completed, fit status, diagnostics, blockers).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from geotestlab.power import (
    CONTROLLED_FIT_SCENARIOS,
    PowerConfig,
    analytic_power,
    analytic_total_variance,
    build_date_keyed_matrix,
    build_fit_scenario,
    build_placebo_windows,
    child_rngs,
    clopper_pearson,
    compare_bayesian_evidence,
    compare_fit_methods,
    critical_values,
    find_mde,
    fit_ar1,
    fit_counterfactual,
    generate_synthetic_case,
    model_simulation,
    placebo_empirical,
    power_from_totals,
    project_counterfactual,
    residual_simulation,
    run_power_analysis,
    validate_detection_criterion,
    validate_mde_config,
)
from geotestlab.power.methods import _bootstrap_ar1_parameters, _moving_block_bootstrap, _shift
from geotestlab.power.service import _split_case
from geotestlab.power.synthetic import TEST_REGION

N_PRE = 120
N_TEST = 12
RHO = 0.4
SIGMA = 2.0
CF_SUM = None  # set per case


def _case(effect_pct=0.0, effect_abs=None, shape="step", rho=RHO, seed=0):
    case = generate_synthetic_case(
        n_pre=N_PRE,
        n_test=N_TEST,
        rho=rho,
        sigma=SIGMA,
        control_betas={"C1": 1.0, "C2": 2.0},
        test_coeffs={"C1": 1.5, "C2": 0.5},
        b0=100.0,
        effect_pct=effect_pct,
        effect_abs=effect_abs,
        shape=shape,
        seed=seed,
        base_controls={"C1": 10.0, "C2": 10.0},
        sd_control_noise=1.0,
    )
    return case


def _config(**over):
    kw = dict(
        method="model_simulation",
        n_simulations=2000,
        random_seed=7,
        alpha=0.05,
        target_power=0.80,
        mde_bounds=(0.0, 50.0),
        mde_tolerance=0.5,
        test_regions=("T",),
        control_regions=("C1", "C2"),
    )
    kw.update(over)
    return PowerConfig(**kw)


# ---------------------------------------------------------------------------
# Generator truth
# ---------------------------------------------------------------------------
class TestSyntheticTruth:
    def test_counterfactual_is_exact_linear_combination(self):
        case = _case()
        assert case.truth["cf_sum_test"] > 0
        # y = cf + e over pre (no effect)
        assert np.allclose(
            case.cf[:N_PRE],
            case.truth["b0"]
            + 1.5 * case.df[case.df["region"] == "C1"]["kpi"].to_numpy()[:N_PRE]
            + 0.5 * case.df[case.df["region"] == "C2"]["kpi"].to_numpy()[:N_PRE],
        )

    def test_analytic_total_variance_matches_simulation(self):
        # Compare the closed form to a direct stationary-autocovariance sum.
        var_single = SIGMA**2 / (1 - RHO**2)
        direct = var_single * (N_TEST + 2 * sum((N_TEST - k) * RHO**k for k in range(1, N_TEST)))
        assert analytic_total_variance(RHO, SIGMA, N_TEST) == pytest.approx(direct)

    def test_effect_injection_relative(self):
        case = _case(effect_pct=10.0)
        y = case.df[case.df["region"] == TEST_REGION]["kpi"].to_numpy()
        rel = (y[N_PRE:] - case.cf[N_PRE:]) / case.cf[N_PRE:]
        assert np.mean(rel) == pytest.approx(0.10, abs=0.05)

    def test_effect_injection_absolute(self):
        case = _case(effect_abs=50.0)
        y = case.df[case.df["region"] == TEST_REGION]["kpi"].to_numpy()
        shift = y[N_PRE:] - case.cf[N_PRE:]
        assert np.mean(shift) == pytest.approx(50.0, abs=5.0)


# ---------------------------------------------------------------------------
# Analytic power sanity
# ---------------------------------------------------------------------------
class TestAnalyticPower:
    def test_matches_brute_force_normal(self):
        mean, sd = 1000.0, 10.0
        rng = np.random.default_rng(0)
        null = rng.normal(mean, sd, 200000)
        alt = rng.normal(mean + 20.0, sd, 200000)
        empirical = np.mean(alt > np.percentile(null, 95))
        theoretical = analytic_power(mean, sd, 20.0, 0.05, "one_sided_positive")
        assert abs(empirical - theoretical) < 0.01

    def test_monotonic_and_bounded(self):
        mean, sd = 1000.0, 10.0
        powers = [analytic_power(mean, sd, s, 0.05, "one_sided_positive") for s in (0, 10, 20, 40)]
        assert powers[0] == pytest.approx(0.05)
        assert all(b >= a for a, b in zip(powers, powers[1:]))

    def test_twosided_lower_than_onesided(self):
        mean, sd = 1000.0, 10.0
        two = analytic_power(mean, sd, 20.0, 0.05, "two_sided")
        one = analytic_power(mean, sd, 20.0, 0.05, "one_sided_positive")
        assert two < one


# ---------------------------------------------------------------------------
# Model-based simulation vs analytic power
# ---------------------------------------------------------------------------
class TestModelSimulation:
    def test_power_matches_analytic(self):
        """Given the prototype's OWN fitted null (mean/sd), the detection and
        effect-injection machinery must reproduce the analytic power tightly.
        The noise model itself is validated separately (rho/sigma recovery)."""
        case = _case()
        cfg = _config()
        res = run_power_analysis(case.df, N_PRE, cfg)
        assert res.method == "model_simulation"
        for e in (0.25, 0.5, 1.0, 2.0):
            shift = res.null_mean * e / 100.0
            theo = analytic_power(res.null_mean, res.null_sd, shift, cfg.alpha, cfg.side)
            i = int(np.argmin(np.abs(res.effect_grid - e)))
            assert abs(res.power_curve[i] - theo) < 0.03, (e, res.power_curve[i], theo)

    def test_null_sd_close_to_truth(self):
        """The fitted AR(1) null should approximate the truth's total sd (loose
        tolerance: rho estimation from ~120 pre-periods has sampling error)."""
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        truth_sd = np.sqrt(analytic_total_variance(RHO, SIGMA, N_TEST))
        assert abs(res.null_sd - truth_sd) / truth_sd < 0.25

    def test_null_calibration(self):
        case = _case(effect_pct=0.0)
        res = run_power_analysis(case.df, N_PRE, _config())
        i0 = 0  # effect 0
        assert abs(res.power_curve[i0] - res.alpha) < 0.02

    def test_ar1_fit_recovers_truth(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        null, alt_fn, meta = model_simulation(pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, 3)
        assert abs(meta["rho_estimate"] - RHO) < 0.2
        assert abs(meta["sigma_estimate"] - SIGMA) < 0.5

    def test_ar_parameter_bootstrap_is_reproducible_for_review(self):
        residuals = np.asarray([0.4, 1.0, 0.2, -0.5, -0.2, 0.7, 1.1, 0.3, -0.4, 0.1])
        first = _bootstrap_ar1_parameters(residuals, 32, np.random.default_rng(17))
        second = _bootstrap_ar1_parameters(residuals, 32, np.random.default_rng(17))
        assert np.array_equal(first[0], second[0])
        assert np.array_equal(first[1], second[1])
        assert len(first[0]) == 32

    def test_higher_rho_lower_power(self):
        res_lo = run_power_analysis(_case(rho=0.2).df, N_PRE, _config())
        res_hi = run_power_analysis(_case(rho=0.7).df, N_PRE, _config())
        i = int(np.argmin(np.abs(res_lo.effect_grid - 0.5)))
        assert res_hi.power_curve[i] < res_lo.power_curve[i] - 0.05


# ---------------------------------------------------------------------------
# Detection criteria
# ---------------------------------------------------------------------------
class TestDetectionCriteria:
    def test_twosided_lower_power_and_calibrated_null(self):
        case = _case()
        one = run_power_analysis(case.df, N_PRE, _config(side="one_sided_positive"))
        two = run_power_analysis(case.df, N_PRE, _config(side="two_sided"))
        assert abs(two.power_curve[0] - 0.05) < 0.02
        i = int(np.argmin(np.abs(one.effect_grid - 0.5)))
        assert two.power_curve[i] < one.power_curve[i]

    # (one-sided-negative behaviour is covered by TestNegativeMDE: the effect
    # magnitude is always non-negative and the direction is controlled by side)


# ---------------------------------------------------------------------------
# Effect injection: relative vs absolute
# ---------------------------------------------------------------------------
class TestInjection:
    def test_absolute_shift_is_constant_total(self):
        case = _case()
        cfg = _config(effect_injection="absolute")
        res = run_power_analysis(case.df, N_PRE, cfg)
        for e in (1.0, 2.0, 4.0):
            theo = analytic_power(res.null_mean, res.null_sd, e * N_TEST, cfg.alpha, cfg.side)
            i = int(np.argmin(np.abs(res.effect_grid - e)))
            assert abs(res.power_curve[i] - theo) < 0.03

    def test_relative_requires_positive_counterfactual(self):
        # A low-volume case where the null total can be <= 0 records failures.
        case = generate_synthetic_case(
            n_pre=N_PRE,
            n_test=N_TEST,
            rho=0.0,
            sigma=8.0,
            control_betas={"C1": 1.0},
            test_coeffs={"C1": 1.0},
            b0=1.0,
            effect_pct=0.0,
            seed=5,
            base_controls={"C1": 1.0},
            sd_control_noise=0.5,
        )
        res = run_power_analysis(
            case.df, N_PRE, _config(n_simulations=500, control_regions=("C1",))
        )
        assert res.completed is True
        assert res.failures >= 0
        assert res.mde_reached is True or res.mde_reached is False  # no crash


# ---------------------------------------------------------------------------
# Effect shape
# ---------------------------------------------------------------------------
class TestEffectShape:
    def test_ramp_reduces_effective_shift(self):
        # A ramp effect (peak e) injects roughly half the total of a step effect.
        case = _case()
        cfg = _config()
        sd = np.sqrt(analytic_total_variance(RHO, SIGMA, N_TEST))
        e = 0.5
        step = analytic_power(
            case.truth["cf_sum_test"],
            sd,
            case.truth["cf_sum_test"] * e / 100.0,
            cfg.alpha,
            cfg.side,
        )
        ramp_shift = case.truth["cf_sum_test"] * e / 100.0 * 0.5
        ramp = analytic_power(case.truth["cf_sum_test"], sd, ramp_shift, cfg.alpha, cfg.side)
        assert ramp < step - 0.05
        assert cfg.effect_shape == "step"


# ---------------------------------------------------------------------------
# MDE search
# ---------------------------------------------------------------------------
class TestMDE:
    def test_mde_recovery(self):
        case = _case()
        cfg = _config()
        res = run_power_analysis(case.df, N_PRE, cfg)
        assert res.mde_reached is True
        assert res.mde is not None
        sd = np.sqrt(analytic_total_variance(RHO, SIGMA, N_TEST))
        # the analytic effect meeting 80% power
        target = cfg.target_power
        theo = None
        for e in np.arange(0.0, 50.0, 0.1):
            p = analytic_power(
                case.truth["cf_sum_test"],
                sd,
                case.truth["cf_sum_test"] * e / 100.0,
                cfg.alpha,
                cfg.side,
            )
            if p >= target:
                theo = e
                break
        assert theo is not None
        assert abs(res.mde - theo) < 1.0

    def test_mde_not_reached_explicit(self):
        case = _case()
        cfg = _config(mde_bounds=(0.0, 0.5))  # tiny bound
        res = run_power_analysis(case.df, N_PRE, cfg)
        assert res.mde_reached is False
        assert res.mde is None
        assert any("MDE not reached" in w for w in res.warnings)

    def test_find_mde_direct(self):
        def power_at(e):
            return 0.9 if e >= 10.0 else 0.1

        mde, reached, _, _ = find_mde(power_at, (0.0, 50.0), 0.8, 0.5)
        assert reached is True
        assert mde == pytest.approx(10.0, abs=0.5)


# ---------------------------------------------------------------------------
# Uncertainty / simulation count
# ---------------------------------------------------------------------------
class TestUncertainty:
    def test_clopper_pearson_contains_true(self):
        lo, hi = clopper_pearson(500, 1000, 0.05)
        assert lo < 0.5 < hi

    def test_clopper_pearson_edges(self):
        assert clopper_pearson(0, 100, 0.05)[0] == 0.0
        assert clopper_pearson(100, 100, 0.05)[1] == 1.0

    def test_power_ci_shrinks_with_n(self):
        case = _case()
        small = run_power_analysis(case.df, N_PRE, _config(n_simulations=300, random_seed=1))
        large = run_power_analysis(case.df, N_PRE, _config(n_simulations=3000, random_seed=1))
        i = int(np.argmin(np.abs(small.effect_grid - 0.5)))
        w_small = small.power_ci_upper[i] - small.power_ci_lower[i]
        w_large = large.power_ci_upper[i] - large.power_ci_lower[i]
        assert w_large < w_small

    def test_power_ci_brackets_empirical_rate(self):
        # The Clopper-Pearson CI brackets the empirical detection rate. It is
        # CONDITIONAL Monte Carlo uncertainty (conditional on the fitted model
        # and the calibration sample), so it is not asserted to contain the
        # analytic power unconditionally (threshold-estimation uncertainty is
        # not covered by this interval).
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(n_simulations=3000))
        i = int(np.argmin(np.abs(res.effect_grid - 0.5)))
        p = res.power_curve[i]
        assert res.power_ci_lower[i] <= p <= res.power_ci_upper[i]
        assert res.power_ci_lower[i] > 0.0
        assert res.power_ci_upper[i] < 1.0


# ---------------------------------------------------------------------------
# Placebo + residual methods
# ---------------------------------------------------------------------------
class TestOtherMethods:
    def test_placebo_null_calibration(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(method="placebo_empirical"))
        assert res.windows_used > 0
        assert abs(res.power_curve[0] - 0.05) < 0.1

    def test_placebo_relative_only(self):
        case = _case()
        with pytest.raises(NotImplementedError):
            run_power_analysis(
                case.df, N_PRE, _config(method="placebo_empirical", effect_injection="absolute")
            )

    def test_residual_simulation_null_calibration_and_power(self):
        case = _case(rho=0.0)  # independent noise suits the bootstrap
        res = run_power_analysis(case.df, N_PRE, _config(method="residual_simulation"))
        assert abs(res.power_curve[0] - 0.05) < 0.02
        i = int(np.argmin(np.abs(res.effect_grid - 0.5)))
        # shift/sd for rho=0: cf_sum*0.5% / (sigma*sqrt(n_test)) ~ 0.99 -> power ~ 0.16
        assert 0.05 < res.power_curve[i] < 0.4

    def test_residual_simulation_records_moving_block_bootstrap(self):
        case = _case(rho=0.0)
        res = run_power_analysis(case.df, N_PRE, _config(method="residual_simulation"))
        assert res.matrix_diagnostics["bootstrap_method"] == "moving_block"
        assert res.matrix_diagnostics["bootstrap_block_length"] >= 2

    def test_moving_block_bootstrap_is_reproducible_and_horizon_safe(self):
        residuals = np.arange(10.0)
        first = _moving_block_bootstrap(residuals, 20, 7, np.random.default_rng(17), block_length=3)
        second = _moving_block_bootstrap(
            residuals, 20, 7, np.random.default_rng(17), block_length=3
        )
        assert np.array_equal(first, second)
        assert first.shape == (20,)

    def test_placebo_windows_function(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        pcts = build_placebo_windows(pre_df, ("T",), ("C1", "C2"), N_TEST)
        assert len(pcts) == N_PRE // N_TEST


# ---------------------------------------------------------------------------
# Policy warnings + result serialisation
# ---------------------------------------------------------------------------
class TestPolicyAndSerialisation:
    def test_short_pre_period_warns(self):
        case = _case()
        res = run_power_analysis(case.df, 8, _config(min_historical_periods=12))
        assert any("pre-period has 8 periods" in w for w in res.warnings)

    def test_low_simulations_warns(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(n_simulations=50, min_simulations=100))
        assert any("n_simulations=50" in w for w in res.warnings)

    def test_result_to_dict_json_safe(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        d = res.to_dict()
        json.dumps(d)
        assert d["method"] == "model_simulation"
        assert d["random_seed"] == 7
        assert isinstance(d["mde"], float)

    def test_unknown_method_rejected(self):
        case = _case()
        with pytest.raises(ValueError):
            run_power_analysis(case.df, N_PRE, _config(method="bogus"))


# ---------------------------------------------------------------------------
# Negative-effect MDE (corrected: direction from side, magnitude non-negative)
# ---------------------------------------------------------------------------
class TestNegativeMDE:
    def test_one_sided_negative_injects_negative_shift(self):
        # A positive magnitude under one_sided_negative injects a NEGATIVE shift
        # (direction controlled by side), so the negative-direction power is
        # symmetric with the positive-direction power and RISES with magnitude.
        # The pre-fix bug injected a positive shift under the negative test and
        # kept power at ~alpha for every magnitude.
        case = _case()
        neg = run_power_analysis(case.df, N_PRE, _config(side="one_sided_negative"))
        pos = run_power_analysis(case.df, N_PRE, _config(side="one_sided_positive"))
        i = int(np.argmin(np.abs(neg.effect_grid - 1.0)))
        assert abs(neg.power_curve[i] - pos.power_curve[i]) < 0.05
        i_small = int(np.argmin(np.abs(neg.effect_grid - 0.25)))
        i_big = int(np.argmin(np.abs(neg.effect_grid - 2.0)))
        assert neg.power_curve[i_big] > neg.power_curve[i_small] + 0.1

    def test_negative_mde_is_non_negative_magnitude(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(side="one_sided_negative"))
        assert res.mde_reached is True
        assert res.mde is not None
        assert res.mde >= 0.0

    def test_negative_and_positive_mde_symmetric(self):
        case = _case()
        pos = run_power_analysis(case.df, N_PRE, _config(side="one_sided_positive"))
        neg = run_power_analysis(case.df, N_PRE, _config(side="one_sided_negative"))
        assert pos.mde is not None and neg.mde is not None
        assert abs(pos.mde - neg.mde) < 1.0

    def test_two_sided_mde_larger_than_one_sided(self):
        case = _case()
        one = run_power_analysis(
            case.df, N_PRE, _config(side="one_sided_positive", mde_tolerance=0.1)
        )
        two = run_power_analysis(case.df, N_PRE, _config(side="two_sided", mde_tolerance=0.1))
        assert one.mde is not None and two.mde is not None
        assert two.mde > one.mde


# ---------------------------------------------------------------------------
# Detection criteria: only implemented criteria, never an unapplied one
# ---------------------------------------------------------------------------
class TestDetectionCriterionGating:
    def test_sign_and_threshold_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="sign_and_threshold"):
            run_power_analysis(case.df, N_PRE, _config(detection_criterion="sign_and_threshold"))

    def test_empirical_placebo_threshold_rejected_for_model(self):
        case = _case()
        with pytest.raises(ValueError, match="placebo_empirical"):
            run_power_analysis(
                case.df, N_PRE, _config(detection_criterion="empirical_placebo_threshold")
            )

    def test_empirical_placebo_threshold_allowed_for_placebo(self):
        case = _case()
        res = run_power_analysis(
            case.df,
            N_PRE,
            _config(
                method="placebo_empirical",
                detection_criterion="empirical_placebo_threshold",
            ),
        )
        assert res.detection_criterion == "empirical_placebo_threshold"
        assert res.completed is True

    def test_exported_criterion_was_applied(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        assert res.detection_criterion == "interval_excludes_zero"


# ---------------------------------------------------------------------------
# Effect shape: step only in the service simulation path
# ---------------------------------------------------------------------------
class TestEffectShapeGating:
    def test_ramp_rejected_in_service(self):
        case = _case()
        with pytest.raises(ValueError, match="ramp"):
            run_power_analysis(case.df, N_PRE, _config(effect_shape="ramp"))

    def test_step_accepted(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(effect_shape="step"))
        assert res.completed is True


# ---------------------------------------------------------------------------
# Independent calibration / alternative / diagnostics streams
# ---------------------------------------------------------------------------
class TestIndependentStreams:
    def test_alt_samples_identical_across_repeated_effect_calls(self):
        # Common random numbers (defect-5 fix): the alternative no-effect
        # sample is drawn ONCE per run and reused across every effect via a
        # deterministic shift, so two calls with the SAME effect must be
        # byte-identical, not merely close.
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        cal_null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 1000, 11
        )
        alt1, _ = alt_fn(0.5, "relative", "one_sided_positive")
        alt2, _ = alt_fn(0.5, "relative", "one_sided_positive")
        assert np.array_equal(alt1, alt2)

    def test_alt_samples_are_deterministic_shift_of_shared_base(self):
        # Two different effects must be a pure additive/multiplicative shift
        # of the SAME underlying noise draw, not independently resampled
        # noise -- i.e. (alt(effect2) - alt(effect1)) is constant across
        # every simulated draw for a relative effect.
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        cal_null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 1000, 11
        )
        alt1, _ = alt_fn(0.5, "relative", "one_sided_positive")
        alt2, _ = alt_fn(2.0, "relative", "one_sided_positive")
        diffs = alt2 - alt1
        assert np.allclose(diffs, diffs[0])

    def test_meta_reports_diagnostics_stream(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        cal_null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, 3
        )
        assert np.isfinite(meta["null_mean"])
        assert np.isfinite(meta["null_sd"])
        assert meta["calibration_simulations"] == 500
        assert meta["detection_simulations"] == 500

    def test_calibration_and_detection_counts_recorded_in_result(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        assert res.calibration_simulations == 2000
        assert res.detection_simulations == 2000
        assert np.isfinite(res.null_mean) and np.isfinite(res.null_sd)


# ---------------------------------------------------------------------------
# Rank deficiency: explicit fallback with recorded reason, never silent
# ---------------------------------------------------------------------------
class TestRankDeficiency:
    @staticmethod
    def _collinear_case():
        case = _case()
        df = case.df.copy()
        c1 = df[df["region"] == "C1"][["date", "kpi"]]
        extra = c1.copy()
        extra["region"] = "C3"
        extra["kpi"] = 2.0 * extra["kpi"]
        extra = extra[["date", "region", "kpi"]]
        return pd.concat([df, extra], ignore_index=True)

    def test_rank_deficient_reported_not_silent(self):
        df = self._collinear_case()
        res = run_power_analysis(df, N_PRE, _config(control_regions=("C1", "C2", "C3")))
        diag = res.matrix_diagnostics
        assert diag["n_observations"] == N_PRE
        assert diag["n_predictors"] == 4  # constant + C1 + C2 + C3
        assert diag["matrix_rank"] < diag["n_predictors"]
        assert diag["fallback_used"] is True
        assert diag["fallback_reason"] in (
            "rank_deficient",
            "underdetermined",
            "ill_conditioned",
        )
        assert res.fit_status == "fallback_constant_mean"
        assert res.fit_method == "constant_mean"
        assert any("constant mean" in w for w in res.warnings)

    def test_full_rank_no_fallback(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        assert res.fit_status == "ok"
        assert res.fit_method == "ols"
        assert res.matrix_diagnostics["fallback_used"] is False
        assert not any("constant mean" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Empty placebo evidence: explicit incomplete result, never [0.0]
# ---------------------------------------------------------------------------
class TestEmptyPlacebo:
    def _run_placebo(self, n_pre, n_test=N_TEST, **config_over):
        case = generate_synthetic_case(
            n_pre=n_pre,
            n_test=n_test,
            rho=RHO,
            sigma=SIGMA,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=0,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        return run_power_analysis(
            case.df,
            n_pre,
            _config(method="placebo_empirical", control_regions=("C1", "C2"), **config_over),
        )

    def test_empty_placebo_incomplete_no_mde(self):
        # 104 pre periods (>= the weekly history floor, so history_status
        # stays "supported") with a 110-period window -> zero placebo
        # windows, isolating the windows-insufficient gate from the
        # Stage-3 history gate.
        res = self._run_placebo(104, n_test=110)
        assert res.completed is False
        assert res.mde is None
        assert res.mde_reached is False
        assert res.safety_diagnostics.get("history_status") == "supported"
        assert res.minimum_window_status == "insufficient"
        assert any("windows" in e for e in res.errors)
        assert any("windows" in b for b in res.blockers)
        assert len(res.power_curve) == 0

    def test_placebo_min_windows_enforced(self):
        # 104 pre periods with 30-period windows -> floor(104/30)=3 windows
        # < minimum 5, again with history_status "supported".
        res = self._run_placebo(104, n_test=30)
        assert res.completed is False
        assert res.mde is None
        assert res.safety_diagnostics.get("history_status") == "supported"
        assert res.minimum_window_status == "insufficient"

    def test_short_history_blocked_before_windows_check(self):
        # Below the weekly history floor, the Stage-3 history gate blocks
        # BEFORE the windows-insufficient check is ever reached (10 periods
        # would also yield zero placebo windows, but history is checked
        # first and is the more specific/informative reason here).
        res = self._run_placebo(10)
        assert res.completed is False
        assert res.mde is None
        assert res.support_status == "blocked"
        assert res.safety_diagnostics.get("history_status") == "blocked"
        assert res.minimum_window_status == "not_applicable"

    def test_residual_simulation_short_history_blocked(self):
        # For residual_simulation, "windows available" IS the retained
        # pre-period observation count -- the same quantity the Stage-3
        # history floor (104) gates. Below that floor, the history gate is
        # always the binding constraint (it is stricter than the default
        # min_placebo_windows=5), so this now blocks via history rather
        # than the old minimum_window_status path.
        case = generate_synthetic_case(
            n_pre=2,
            n_test=N_TEST,
            rho=RHO,
            sigma=SIGMA,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=0,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        res = run_power_analysis(
            case.df, 2, _config(method="residual_simulation", control_regions=("C1", "C2"))
        )
        assert res.completed is False
        assert res.mde is None
        assert res.support_status == "blocked"
        assert res.safety_diagnostics.get("history_status") == "blocked"
        assert res.minimum_window_status == "not_applicable"

    def test_residual_simulation_windows_gate_reachable_above_history_floor(self):
        # The windows-insufficient gate for residual_simulation IS still
        # reachable when min_placebo_windows is configured ABOVE the
        # history floor (104): 120 retained periods passes history but is
        # still fewer than a min_placebo_windows=150 requirement.
        case = _case()
        res = run_power_analysis(
            case.df,
            N_PRE,
            _config(method="residual_simulation", min_placebo_windows=150),
        )
        assert res.completed is False
        assert res.mde is None
        assert res.safety_diagnostics.get("history_status") == "supported"
        assert res.minimum_window_status == "insufficient"


# ---------------------------------------------------------------------------
# Date alignment: date-keyed matrix with structured diagnostics
# ---------------------------------------------------------------------------
class TestDateAlignment:
    def test_missing_control_dates_reported(self):
        case = _case()
        df = case.df.copy()
        drop = list(df["date"].unique()[10:15])
        df = df[~((df["region"] == "C2") & (df["date"].isin(drop)))]
        res = run_power_analysis(df, N_PRE, _config())
        diag = res.matrix_diagnostics
        assert diag["controls_with_missing_dates"]["C2"] == 5
        assert diag["dates_removed"] == 0  # test region stays complete
        assert res.completed is True

    def test_duplicate_region_date_keys_blocked(self):
        # Duplicate (region, date) keys among the SELECTED regions must
        # block the analysis rather than being silently resolved by whichever
        # row the pivot's aggfunc="first" happens to keep.
        case = _case()
        dup = case.df.iloc[:5].copy()
        df = pd.concat([case.df, dup], ignore_index=True)
        res = run_power_analysis(df, N_PRE, _config())
        assert res.completed is False
        assert res.mde is None
        assert any("duplicate" in b.lower() for b in res.blockers)

    def test_duplicate_keys_blocked_regardless_of_row_order(self):
        # Row order must never decide the analytical value: shuffling the
        # duplicate-containing frame still blocks (never silently completes
        # with a different value depending on which duplicate row landed
        # first in the pivot).
        case = _case()
        dup = case.df.iloc[:5].copy()
        df = pd.concat([case.df, dup], ignore_index=True)
        shuffled = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
        res_a = run_power_analysis(df, N_PRE, _config())
        res_b = run_power_analysis(shuffled, N_PRE, _config())
        assert res_a.completed is False
        assert res_b.completed is False

    def test_duplicate_keys_outside_selected_regions_do_not_block(self):
        # A duplicate key on a region that is NOT selected as test or control
        # is irrelevant to this analysis and must not block it.
        case = _case()
        other = case.df[case.df["region"] == "C2"].iloc[:3].copy()
        other["region"] = "UNRELATED"
        dup_of_other = other.iloc[:2].copy()
        df = pd.concat([case.df, other, dup_of_other], ignore_index=True)
        res = run_power_analysis(df, N_PRE, _config())
        assert res.completed is True

    def test_shuffled_rows_identical_result(self):
        case = _case()
        shuffled = case.df.sample(frac=1.0, random_state=0).reset_index(drop=True)
        a = run_power_analysis(case.df, N_PRE, _config())
        b = run_power_analysis(shuffled, N_PRE, _config())
        assert np.allclose(a.power_curve, b.power_curve)
        assert a.mde == b.mde

    def test_unequal_region_lengths(self):
        case = _case()
        df = case.df.copy()
        drop = list(df["date"].unique()[5:9])
        df = df[~((df["region"] == "C1") & (df["date"].isin(drop)))]
        res = run_power_analysis(df, N_PRE, _config())
        assert res.matrix_diagnostics["controls_with_missing_dates"]["C1"] == 4
        assert res.completed is True

    def test_continuity_reported(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        assert "continuity" in res.matrix_diagnostics


# ---------------------------------------------------------------------------
# Explicit selected design (no hardcoded TEST_REGION in the service)
# ---------------------------------------------------------------------------
class TestExplicitDesign:
    def test_test_regions_required(self):
        case = _case()
        with pytest.raises(ValueError, match="test_regions"):
            run_power_analysis(case.df, N_PRE, _config(test_regions=()))

    def test_control_regions_required(self):
        case = _case()
        with pytest.raises(ValueError, match="control_regions"):
            run_power_analysis(case.df, N_PRE, _config(control_regions=()))

    def test_overlapping_test_control_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="both test and control"):
            run_power_analysis(
                case.df,
                N_PRE,
                _config(test_regions=("T", "C1"), control_regions=("C1", "C2")),
            )

    def test_missing_region_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="not present in data"):
            run_power_analysis(case.df, N_PRE, _config(control_regions=("C1", "C2", "NOPE")))

    def test_multiple_test_regions_aggregated_by_sum(self):
        case = _case()
        df = case.df.copy()
        t = df[df["region"] == TEST_REGION].copy()
        t2 = t.copy()
        t2["region"] = "T2"
        t2["kpi"] = t2["kpi"] + 7.0
        df = pd.concat([df, t2], ignore_index=True)
        test, controls, diag = build_date_keyed_matrix(df, ("T", "T2"), ("C1", "C2"))
        t_series = (
            df[df["region"].isin(("T", "T2"))].groupby("date")["kpi"].sum().reindex(test.index)
        )
        assert np.allclose(test.to_numpy(), t_series.to_numpy())
        res = run_power_analysis(
            df, N_PRE, _config(test_regions=("T", "T2"), control_regions=("C1", "C2"))
        )
        assert res.completed is True

    def test_explicit_test_dates_used(self):
        case = _case()
        all_dates = sorted(case.df["date"].unique())
        short = list(all_dates[-6:])
        res_short = run_power_analysis(case.df, N_PRE, _config(test_dates=tuple(short)))
        res_long = run_power_analysis(case.df, N_PRE, _config())
        i = int(np.argmin(np.abs(res_short.effect_grid - 1.0)))
        assert res_short.completed is True
        # fewer test periods -> less evidence -> lower power at the same effect
        assert res_short.power_curve[i] < res_long.power_curve[i]


# ---------------------------------------------------------------------------
# Fit-method comparison evidence (OLS vs Elastic Net vs LASSO)
# ---------------------------------------------------------------------------
class TestFitComparison:
    def test_comparison_runs_all_scenarios(self):
        for scenario in CONTROLLED_FIT_SCENARIOS:
            case, test_regions, controls = build_fit_scenario(scenario)
            out = compare_fit_methods(case, test_regions, controls, scenario=scenario)
            assert len(out["results"]) == 3
            assert [r["fit_method"] for r in out["results"]] == ["ols", "elastic_net", "lasso"]
            json.dumps(out)  # JSON-safe evidence

    def test_comparison_deterministic(self):
        case, test_regions, controls = build_fit_scenario("baseline")
        a = compare_fit_methods(case, test_regions, controls, scenario="baseline")
        b = compare_fit_methods(case, test_regions, controls, scenario="baseline")
        assert a == b

    def test_ols_recovers_truth_when_full_rank(self):
        case, test_regions, controls = build_fit_scenario("baseline")
        out = compare_fit_methods(case, test_regions, controls, scenario="baseline")
        ols = next(r for r in out["results"] if r["fit_method"] == "ols")
        assert abs(ols["cf_sum_error_pct"]) < 5.0

    def test_collinearity_evidence_recorded(self):
        case, test_regions, controls = build_fit_scenario("collinearity")
        out = compare_fit_methods(case, test_regions, controls, scenario="collinearity")
        ols = next(r for r in out["results"] if r["fit_method"] == "ols")
        cond = ols["condition_number"]
        assert ols["fallback_reason"] is not None or (cond is not None and cond > 100)

    def test_short_history_diagnostics(self):
        case, test_regions, controls = build_fit_scenario("short_history")
        out = compare_fit_methods(case, test_regions, controls, scenario="short_history")
        ols = next(r for r in out["results"] if r["fit_method"] == "ols")
        assert ols["n_predictors"] == 3
        assert ols["matrix_rank"] <= ols["n_predictors"]

    def test_omitted_control_leaves_residual_structure(self):
        # Omitting a true control leaves part of its contribution in the
        # residuals: the OLS residual sd is larger than the baseline fit's.
        base_case, base_t, base_c = build_fit_scenario("baseline")
        case, test_regions, controls = build_fit_scenario("omitted_control")
        base_out = compare_fit_methods(base_case, base_t, base_c, scenario="baseline")
        out = compare_fit_methods(case, test_regions, controls, scenario="omitted_control")
        base_ols = next(r for r in base_out["results"] if r["fit_method"] == "ols")
        omitted_ols = next(r for r in out["results"] if r["fit_method"] == "ols")
        assert np.isfinite(omitted_ols["cf_sum_error_pct"])
        assert omitted_ols["residual_sd"] is not None
        assert omitted_ols["residual_sd"] > base_ols["residual_sd"]


# ---------------------------------------------------------------------------
# Structured result contract
# ---------------------------------------------------------------------------
class TestResultContract:
    def test_structured_fields_present(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        assert res.completed is True
        assert res.fit_status == "ok"
        assert res.fit_method == "ols"
        assert res.calibration_simulations == 2000
        assert res.detection_simulations == 2000
        assert res.minimum_history_status == "ok"
        assert res.minimum_window_status == "not_applicable"
        assert res.errors == ()
        assert res.blockers == ()
        assert res.methodology_version
        for key in ("n_observations", "n_predictors", "matrix_rank", "condition_number"):
            assert key in res.matrix_diagnostics

    def test_minimum_history_status(self):
        # The legacy pre_count-based minimum_history_status field remains a
        # warning-level, informational signal (unchanged): it never blocks by
        # itself. But 8 retained periods is also far below the Stage-3
        # methodology-safety history floor (104 for weekly), which DOES block
        # -- history sufficiency must be a hard gate, not a warning, per the
        # evidence showing an unacceptable power bias below that floor.
        case = _case()
        res = run_power_analysis(case.df, 8, _config(min_historical_periods=12))
        assert res.minimum_history_status == "insufficient"
        assert res.completed is False
        assert res.support_status == "blocked"
        assert res.safety_diagnostics["history_status"] == "blocked"

    def test_history_at_or_above_weekly_floor_not_blocked_by_safety(self):
        # 104 retained weekly periods is the floor itself: history_status must
        # be "supported" (not blocked), isolating the legacy
        # minimum_history_status warning from the new hard safety gate.
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(min_historical_periods=12))
        assert res.minimum_history_status == "ok"
        assert res.safety_diagnostics["history_status"] == "supported"
        assert res.completed is True

    def test_to_dict_includes_structured_fields(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config())
        d = res.to_dict()
        json.dumps(d)
        for key in (
            "completed",
            "fit_status",
            "fit_method",
            "matrix_diagnostics",
            "calibration_simulations",
            "detection_simulations",
            "minimum_history_status",
            "minimum_window_status",
            "methodology_version",
            "errors",
            "blockers",
        ):
            assert key in d


# ---------------------------------------------------------------------------
# Holdout-date leakage: _split_case must never leak post-period observations
# ---------------------------------------------------------------------------
class TestSplitCaseNoLeakage:
    @staticmethod
    def _dates(case):
        return pd.to_datetime(pd.Series(sorted(case.df["date"].unique()))).to_numpy()

    def test_pre_period_is_exactly_first_pre_count(self):
        case = _case()
        all_dates = self._dates(case)
        cfg = _config(test_dates=tuple(all_dates[-6:]))
        pre_df, test_df, n_test = _split_case(case.df, N_PRE, cfg)
        assert set(pre_df["date"].unique()) == set(all_dates[:N_PRE])
        assert n_test == 6

    def test_unselected_post_period_dates_never_enter_fitting(self):
        # Explicit subset of the intended window: the unselected post-period
        # dates must NOT appear in pre_df (that would be holdout leakage).
        case = _case()
        all_dates = self._dates(case)
        selected = tuple(all_dates[N_PRE : N_PRE + 4])
        pre_df, test_df, n_test = _split_case(case.df, N_PRE, _config(test_dates=selected))
        assert set(pre_df["date"].unique()) == set(all_dates[:N_PRE])
        assert set(test_df["date"].unique()) == set(selected)
        assert n_test == 4
        assert not (set(pre_df["date"].unique()) & set(test_df["date"].unique()))
        # every unselected post-period date is excluded entirely, not leaked
        excluded = set(all_dates[N_PRE:]) - set(selected)
        assert excluded.isdisjoint(pre_df["date"].unique())

    def test_pre_period_date_in_test_dates_rejected(self):
        case = _case()
        all_dates = self._dates(case)
        bad = tuple([all_dates[N_PRE - 1], all_dates[N_PRE]])
        with pytest.raises(ValueError, match="subset of the intended test window"):
            _split_case(case.df, N_PRE, _config(test_dates=bad))

    def test_absent_date_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="not present in the data"):
            _split_case(case.df, N_PRE, _config(test_dates=("2020-01-01",)))

    def test_duplicate_test_dates_rejected(self):
        case = _case()
        all_dates = self._dates(case)
        dup = tuple([all_dates[N_PRE], all_dates[N_PRE]])
        with pytest.raises(ValueError, match="duplicate"):
            _split_case(case.df, N_PRE, _config(test_dates=dup))

    def test_unsorted_test_dates_accepted(self):
        case = _case()
        all_dates = self._dates(case)
        window = all_dates[N_PRE : N_PRE + 4]
        pre_df, test_df, n_test = _split_case(
            case.df, N_PRE, _config(test_dates=tuple(window[::-1]))
        )
        assert n_test == 4
        assert set(test_df["date"].unique()) == set(window)

    def test_empty_retained_window_is_incomplete(self):
        # pre_count covering every date -> no intended test window left.
        case = _case()
        res = run_power_analysis(case.df, len(self._dates(case)), _config(n_simulations=300))
        assert res.completed is False
        assert res.mde is None
        assert any("at least one date" in b for b in res.blockers)
        assert len(res.power_curve) == 0

    def test_coefficient_leakage_absent(self):
        # The counterfactual fit sees exactly pre_count periods: no post-period
        # row can enter the fitted residuals even when test_dates is a subset.
        case = _case()
        all_dates = self._dates(case)
        cfg = _config(test_dates=tuple(all_dates[N_PRE : N_PRE + 4]), n_simulations=500)
        res = run_power_analysis(case.df, N_PRE, cfg)
        assert res.completed is True
        assert res.matrix_diagnostics["n_observations"] == N_PRE
        assert res.windows_available == N_PRE


# ---------------------------------------------------------------------------
# NumPy 1.24 compatibility: SeedSequence-based independent streams
# ---------------------------------------------------------------------------
class TestChildRngs:
    def test_derives_three_independent_streams(self):
        rngs = child_rngs(42, 3)
        assert len(rngs) == 3
        draws = [r.normal(size=100) for r in rngs]
        assert not np.array_equal(draws[0], draws[1])
        assert not np.array_equal(draws[1], draws[2])

    def test_reproducible(self):
        a = [r.normal(size=50) for r in child_rngs(7, 3)]
        b = [r.normal(size=50) for r in child_rngs(7, 3)]
        for x, y in zip(a, b):
            assert np.array_equal(x, y)

    def test_matches_generator_spawn_children(self):
        # The SeedSequence path must equal default_rng(seed).spawn(n) children
        # so behaviour is identical to the NumPy >= 1.25 path.
        seq = np.random.SeedSequence(99)
        expected = [np.random.default_rng(c) for c in seq.spawn(3)]
        got = child_rngs(99, 3)
        assert np.array_equal(expected[0].normal(size=40), got[0].normal(size=40))
        assert np.array_equal(expected[2].normal(size=40), got[2].normal(size=40))

    def test_accepts_seed_sequence(self):
        seq = np.random.SeedSequence(123)
        a = [r.normal(size=30) for r in child_rngs(seq, 2)]
        b = [r.normal(size=30) for r in child_rngs(123, 2)]
        for x, y in zip(a, b):
            assert np.array_equal(x, y)

    def test_monte_carlo_methods_accept_integer_seed(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        null, alt_fn, meta = model_simulation(pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 300, 5)
        assert len(null) == 300
        assert np.isfinite(meta["null_mean"])
        null_r, _, meta_r = residual_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 300, 5
        )
        assert len(null_r) == 300
        assert np.isfinite(meta_r["null_mean"])


# ---------------------------------------------------------------------------
# Empirical-placebo direction: side controls the sign of the shift
# ---------------------------------------------------------------------------
class TestPlaceboNegativeDirection:
    def test_negative_placebo_power_rises_with_magnitude(self):
        # Pre-fix: the empirical placebo alternative ignored side, so the
        # negative-side power stayed at ~alpha for every magnitude.
        case = _case()
        neg = run_power_analysis(
            case.df, N_PRE, _config(method="placebo_empirical", side="one_sided_negative")
        )
        assert neg.completed is True
        i_small = int(np.argmin(np.abs(neg.effect_grid - 0.5)))
        i_big = int(np.argmin(np.abs(neg.effect_grid - 5.0)))
        assert neg.power_curve[i_big] > neg.power_curve[i_small] + 0.1

    def test_negative_placebo_mde_is_non_negative_magnitude(self):
        case = _case()
        res = run_power_analysis(
            case.df, N_PRE, _config(method="placebo_empirical", side="one_sided_negative")
        )
        assert res.mde_reached is True
        assert res.mde is not None
        assert res.mde >= 0.0

    def test_negative_and_positive_placebo_symmetric(self):
        case = _case()
        pos = run_power_analysis(
            case.df, N_PRE, _config(method="placebo_empirical", side="one_sided_positive")
        )
        neg = run_power_analysis(
            case.df, N_PRE, _config(method="placebo_empirical", side="one_sided_negative")
        )
        i = int(np.argmin(np.abs(neg.effect_grid - 2.0)))
        assert abs(neg.power_curve[i] - pos.power_curve[i]) < 0.1

    def test_twosided_placebo_default_positive_shift(self):
        # two_sided uses the documented default signed shift (positive) with
        # two-tailed detection. The empirical null is coarse (10 windows), so
        # the two-tailed power at effect 0 is only approximately alpha.
        case = _case()
        res = run_power_analysis(
            case.df, N_PRE, _config(method="placebo_empirical", side="two_sided")
        )
        assert res.completed is True
        assert abs(res.power_curve[0] - 0.05) < 0.3

    def test_alt_fn_direction_by_side(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        null, alt_fn, _ = placebo_empirical(pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 0, 0)
        pos, _ = alt_fn(5.0, "relative", "one_sided_positive")
        neg, _ = alt_fn(5.0, "relative", "one_sided_negative")
        two, _ = alt_fn(5.0, "relative", "two_sided")
        assert np.all(pos > null)
        assert np.all(neg < null)
        assert np.all(two > null)  # documented default positive shift


# ---------------------------------------------------------------------------
# MDE configuration validation (before any simulation)
# ---------------------------------------------------------------------------
class TestMDEConfigValidation:
    def test_valid_config_passes(self):
        validate_mde_config((0.0, 50.0), 0.8, 0.5, alpha=0.05, n_simulations=1000)

    def test_negative_lower_bound_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="non-negative"):
            run_power_analysis(case.df, N_PRE, _config(mde_bounds=(-1.0, 50.0)))

    def test_upper_bound_equal_lower_rejected(self):
        with pytest.raises(ValueError, match="upper bound"):
            validate_mde_config((10.0, 10.0), 0.8, 0.5)

    def test_upper_bound_below_lower_rejected(self):
        with pytest.raises(ValueError, match="upper bound"):
            validate_mde_config((20.0, 5.0), 0.8, 0.5)

    def test_non_positive_tolerance_rejected(self):
        with pytest.raises(ValueError, match="tolerance"):
            validate_mde_config((0.0, 50.0), 0.8, 0.0)
        with pytest.raises(ValueError, match="tolerance"):
            validate_mde_config((0.0, 50.0), 0.8, -1.0)

    def test_target_power_out_of_range_rejected(self):
        for bad in (0.0, 1.0, -0.5, 1.5):
            with pytest.raises(ValueError, match="target_power"):
                validate_mde_config((0.0, 50.0), bad, 0.5)

    def test_alpha_out_of_range_rejected(self):
        for bad in (0.0, 1.0, -0.1, 1.1):
            with pytest.raises(ValueError, match="alpha"):
                validate_mde_config((0.0, 50.0), 0.8, 0.5, alpha=bad)

    def test_n_simulations_non_positive_rejected(self):
        with pytest.raises(ValueError, match="n_simulations"):
            validate_mde_config((0.0, 50.0), 0.8, 0.5, n_simulations=0)
        with pytest.raises(ValueError, match="n_simulations"):
            validate_mde_config((0.0, 50.0), 0.8, 0.5, n_simulations=-10)

    def test_non_finite_bounds_rejected(self):
        # NaN/inf bounds must fail before simulation (a non-finite effect grid
        # would otherwise produce meaningless power/MDE values).
        for bad in (
            (0.0, float("nan")),
            (float("nan"), 50.0),
            (0.0, float("inf")),
            (float("-inf"), 50.0),
            (float("nan"), float("inf")),
        ):
            with pytest.raises(ValueError, match="finite"):
                validate_mde_config(bad, 0.8, 0.5)

    def test_non_finite_tolerance_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="finite"):
                validate_mde_config((0.0, 50.0), 0.8, bad)

    def test_non_finite_target_power_rejected(self):
        for bad in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match="target_power"):
                validate_mde_config((0.0, 50.0), bad, 0.5)

    def test_service_rejects_non_finite_bounds_before_simulation(self):
        case = _case()
        with pytest.raises(ValueError, match="finite"):
            run_power_analysis(case.df, N_PRE, _config(mde_bounds=(0.0, float("inf"))))

    def test_service_rejects_invalid_bounds_before_simulation(self):
        case = _case()
        with pytest.raises(ValueError, match="non-negative"):
            run_power_analysis(case.df, N_PRE, _config(mde_bounds=(-5.0, 50.0)))

    def test_find_mde_rejects_invalid_bounds(self):
        with pytest.raises(ValueError, match="upper bound"):
            find_mde(lambda e: 0.9, (10.0, 10.0), 0.8, 0.5)


# ---------------------------------------------------------------------------
# Service validation branches (fit method / injection / side / empty window)
# ---------------------------------------------------------------------------
class TestServiceValidationBranches:
    def test_unknown_fit_method_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="Unknown fit method"):
            run_power_analysis(case.df, N_PRE, _config(fit_method="ridge"))

    def test_unknown_effect_injection_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="Unknown effect injection"):
            run_power_analysis(case.df, N_PRE, _config(effect_injection="bogus"))

    def test_unknown_side_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="Unknown side"):
            run_power_analysis(case.df, N_PRE, _config(side="bogus"))

    def test_no_test_window_returns_incomplete(self):
        # pre_count == total dates -> empty intended test window.
        case = _case()
        total = len(case.df["date"].unique())
        res = run_power_analysis(case.df, total, _config(n_simulations=300))
        assert res.completed is False
        assert len(res.power_curve) == 0
        assert any("at least one date" in b for b in res.blockers)

    def test_negative_baseline_blocks_relative_injection(self):
        # A case whose counterfactual test-window total is negative makes
        # "effect/100 of the baseline" undefined for a relative effect. This
        # must block explicitly rather than silently censoring individual
        # simulated draws by their own sign (which used to report a
        # misleadingly well-formed power=0 result).
        case = generate_synthetic_case(
            n_pre=N_PRE,
            n_test=N_TEST,
            rho=0.0,
            sigma=2.0,
            control_betas={"C1": 1.0},
            test_coeffs={"C1": -2.0},
            b0=5.0,
            effect_pct=0.0,
            seed=3,
            base_controls={"C1": 10.0},
            sd_control_noise=1.0,
        )
        res = run_power_analysis(
            case.df,
            N_PRE,
            _config(n_simulations=300, control_regions=("C1",), effect_injection="relative"),
        )
        assert res.completed is False
        assert res.mde is None
        assert len(res.power_curve) == 0
        assert any("baseline" in b.lower() for b in res.blockers)

    def test_negative_baseline_absolute_injection_still_completes(self):
        # The same non-positive-baseline case is well-defined under absolute
        # injection (a flat per-period shift never references the baseline
        # sign), so it must NOT be blocked.
        case = generate_synthetic_case(
            n_pre=N_PRE,
            n_test=N_TEST,
            rho=0.0,
            sigma=2.0,
            control_betas={"C1": 1.0},
            test_coeffs={"C1": -2.0},
            b0=5.0,
            effect_pct=0.0,
            seed=3,
            base_controls={"C1": 10.0},
            sd_control_noise=1.0,
        )
        res = run_power_analysis(
            case.df,
            N_PRE,
            _config(
                n_simulations=300,
                control_regions=("C1",),
                effect_injection="absolute",
                mde_bounds=(0.0, 50.0),
            ),
        )
        assert res.completed is True
        assert res.failures == 0


# ---------------------------------------------------------------------------
# Counterfactual fit branch coverage
# ---------------------------------------------------------------------------
class TestFitCounterfactualBranches:
    def _pre_df(self, df, n_pre=N_PRE):
        return df[df["date"] < df["date"].unique()[n_pre]]

    def test_underdetermined_falls_back(self):
        case = generate_synthetic_case(
            n_pre=3,
            n_test=2,
            rho=0.0,
            sigma=1.0,
            control_betas={"C1": 1.0, "C2": 2.0, "C3": 0.5, "C4": 1.5},
            test_coeffs={"C1": 1.0, "C2": 0.5, "C3": 0.5, "C4": 0.5},
            b0=50.0,
            seed=0,
            base_controls={"C1": 10.0, "C2": 10.0, "C3": 10.0, "C4": 10.0},
            sd_control_noise=1.0,
        )
        fit = fit_counterfactual(self._pre_df(case.df, 3), ("T",), ("C1", "C2", "C3", "C4"))
        assert fit.fit_status == "fallback_constant_mean"
        assert fit.diagnostics["fallback_reason"] == "underdetermined"

    def test_no_observations_falls_back(self):
        case = _case()
        empty = self._pre_df(case.df)[
            self._pre_df(case.df)["date"].isin(pd.to_datetime(["2020-01-01"]))
        ]
        fit = fit_counterfactual(empty, ("T",), ("C1", "C2"))
        assert fit.fit_status == "fallback_constant_mean"
        assert fit.diagnostics["fallback_reason"] == "no_observations"
        assert len(fit.residuals) == 0

    def test_ill_conditioned_falls_back_when_condition_limit_low(self):
        # A full-rank design with a tiny condition-number limit forces the
        # ill_conditioned fallback (rank is full but cond > limit).
        case = _case()
        fit = fit_counterfactual(
            self._pre_df(case.df), ("T",), ("C1", "C2"), max_condition_number=1.0
        )
        assert fit.fit_status == "fallback_constant_mean"
        assert fit.diagnostics["fallback_reason"] == "ill_conditioned"

    def test_duplicate_columns_sanitised_not_fallback(self):
        # An exact-duplicate control is removed BEFORE the rank/condition
        # check, not left to trigger a full constant-mean fallback -- the
        # remaining (here, zero other) informative controls are preserved.
        case = _case()
        df = case.df.copy()
        c1 = df[df["region"] == "C1"][["date", "kpi"]].copy()
        c3 = c1.copy()
        c3["region"] = "C3"  # exact duplicate of C1
        df = pd.concat([df, c3], ignore_index=True)
        fit = fit_counterfactual(self._pre_df(df), ("T",), ("C1", "C3"))
        removed = fit.diagnostics["removed_controls"]
        assert {"region": "C3", "reason": "duplicate_of:C1"} in removed
        assert fit.diagnostics["retained_control_regions"] == ["C1"]
        assert fit.fit_status == "ok"
        assert fit.fit_method == "ols"
        # No unsanitised duplicate pair should remain in the design actually
        # fitted.
        assert fit.diagnostics["duplicate_predictor_pairs"] == []

    def test_duplicate_control_with_other_informative_controls_preserved(self):
        # Two informative controls plus one exact duplicate of one of them:
        # the duplicate is dropped, C1 and C2 are both still fitted (never a
        # full fallback just because ONE control was redundant).
        case = _case()
        df = case.df.copy()
        c1 = df[df["region"] == "C1"][["date", "kpi"]].copy()
        c1_dup = c1.copy()
        c1_dup["region"] = "C1_DUP"
        df = pd.concat([df, c1_dup], ignore_index=True)
        fit = fit_counterfactual(self._pre_df(df), ("T",), ("C1", "C2", "C1_DUP"))
        assert fit.fit_status == "ok"
        assert sorted(fit.diagnostics["retained_control_regions"]) == ["C1", "C2"]
        assert {"region": "C1_DUP", "reason": "duplicate_of:C1"} in fit.diagnostics[
            "removed_controls"
        ]

    def test_constant_control_sanitised(self):
        case = _case()
        df = case.df.copy()
        const_col = df[df["region"] == "C1"][["date"]].copy()
        const_col["region"] = "FLAT"
        const_col["kpi"] = 5.0
        df = pd.concat([df, const_col], ignore_index=True)
        fit = fit_counterfactual(self._pre_df(df), ("T",), ("C1", "C2", "FLAT"))
        assert fit.fit_status == "ok"
        assert "FLAT" not in fit.diagnostics["retained_control_regions"]
        assert {"region": "FLAT", "reason": "constant"} in fit.diagnostics["removed_controls"]

    def test_only_constant_controls_falls_back_with_explicit_reason(self):
        case = _case()
        df = case.df.copy()
        flat1 = df[df["region"] == "C1"][["date"]].copy()
        flat1["region"] = "FLAT1"
        flat1["kpi"] = 5.0
        flat2 = flat1.copy()
        flat2["region"] = "FLAT2"
        flat2["kpi"] = 9.0
        df = pd.concat([df, flat1, flat2], ignore_index=True)
        fit = fit_counterfactual(self._pre_df(df), ("T",), ("FLAT1", "FLAT2"))
        assert fit.fit_status == "fallback_constant_mean"
        assert fit.diagnostics["fallback_reason"] == "no_informative_controls_after_sanitisation"

    def test_projection_uses_sanitised_control_set(self):
        # The test-window projection must use the SAME sanitised control set
        # the fit was trained on; a stale duplicate column reference would
        # otherwise mismatch the fitted coefficients/model.
        case = _case()
        df = case.df.copy()
        c1 = df[df["region"] == "C1"][["date", "kpi"]].copy()
        c3 = c1.copy()
        c3["region"] = "C3"
        df = pd.concat([df, c3], ignore_index=True)
        pre_df = self._pre_df(df)
        test_df = df[df["date"] >= df["date"].unique()[N_PRE]]
        fit = fit_counterfactual(pre_df, ("T",), ("C1", "C3"))
        projected, retained_dates, window_diag = project_counterfactual(
            fit, test_df, ("T",), ("C1", "C3")
        )
        assert len(projected) == len(retained_dates) == N_TEST
        assert np.all(np.isfinite(projected))

    def test_unknown_fit_method_rejected(self):
        case = _case()
        with pytest.raises(ValueError, match="Unknown fit method"):
            fit_counterfactual(self._pre_df(case.df), ("T",), ("C1", "C2"), fit_method="ridge")

    def test_elastic_net_and_lasso_with_no_controls(self):
        # X_no_const empty path for sklearn fits (constant-mean model, no fit).
        case = _case()
        for m in ("elastic_net", "lasso"):
            fit = fit_counterfactual(self._pre_df(case.df), ("T",), (), fit_method=m)
            assert fit.fit_status == "ok"
            assert fit.model is None
            assert len(fit.coef) == 1

    def test_fit_ar1_short_and_constant(self):
        assert fit_ar1(np.array([])) == (0.0, 0.0)
        assert fit_ar1(np.array([1.0]))[0] == 0.0
        assert fit_ar1(np.array([1.0, 2.0]))[0] == 0.0
        rho, sigma = fit_ar1(np.full(10, 5.0))
        assert rho == 0.0
        assert sigma == 0.0

    def test_residual_simulation_no_observations(self):
        # 0 retained pre-period observations is far below the weekly history
        # floor (104): the methodology safety policy now blocks explicitly
        # instead of silently bootstrapping n_sim zeros from an empty
        # residual array (which would have reported a well-formed but
        # meaningless zero-variance null).
        case = _case()
        empty_pre = self._pre_df(case.df)[
            self._pre_df(case.df)["date"].isin(pd.to_datetime(["2020-01-01"]))
        ]
        null, alt_fn, meta = residual_simulation(
            empty_pre, case.df, ("T",), ("C1", "C2"), N_TEST, 100, 0
        )
        assert len(null) == 0
        assert meta["windows_available"] == 0
        assert meta["blocked"] is True
        assert "history" in meta["matrix_diagnostics"]["safety"]["reasons"][0]


# ---------------------------------------------------------------------------
# Detection helpers: all sides and criterion gating
# ---------------------------------------------------------------------------
class TestDetectionHelpers:
    def test_power_from_totals_all_sides(self):
        rng = np.random.default_rng(0)
        null = rng.normal(1000, 10, 200000)
        alt = rng.normal(1040, 10, 200000)  # strong positive shift
        p_pos = power_from_totals(null, alt, "one_sided_positive", 0.05)
        p_neg = power_from_totals(null, alt, "one_sided_negative", 0.05)
        p_two = power_from_totals(null, alt, "two_sided", 0.05)
        assert 0.95 < p_pos < 1.0
        assert 0.0 <= p_neg < 0.01  # positive shift detected ~ never on negative side
        assert p_two < p_pos
        # null calibration
        assert abs(power_from_totals(null, null, "two_sided", 0.05) - 0.05) < 0.01
        assert abs(power_from_totals(null, null, "one_sided_positive", 0.05) - 0.05) < 0.01
        assert abs(power_from_totals(null, null, "one_sided_negative", 0.05) - 0.05) < 0.01

    def test_critical_values_all_sides(self):
        null = np.arange(1000, dtype=float)
        lo, hi = critical_values(null, "one_sided_positive", 0.05)
        assert lo == -np.inf and hi == pytest.approx(949.05, abs=0.01)
        lo, hi = critical_values(null, "one_sided_negative", 0.05)
        assert lo == pytest.approx(49.95, abs=0.01) and hi == np.inf
        lo, hi = critical_values(null, "two_sided", 0.05)
        assert lo == pytest.approx(24.975, abs=0.01)
        assert hi == pytest.approx(974.025, abs=0.01)

    def test_unknown_criterion_rejected(self):
        with pytest.raises(ValueError, match="Unknown detection criterion"):
            validate_detection_criterion("bogus")


# ---------------------------------------------------------------------------
# Analytic / generator / uncertainty branch coverage
# ---------------------------------------------------------------------------
class TestAnalyticAndGeneratorBranches:
    def test_analytic_power_two_sided(self):
        mean, sd = 1000.0, 10.0
        two = analytic_power(mean, sd, 20.0, 0.05, "two_sided")
        one = analytic_power(mean, sd, 20.0, 0.05, "one_sided_positive")
        assert 0.0 < two < 1.0
        assert two < one

    def test_analytic_power_one_sided_negative(self):
        mean, sd = 1000.0, 10.0
        neg = analytic_power(mean, sd, -20.0, 0.05, "one_sided_negative")
        pos = analytic_power(mean, sd, 20.0, 0.05, "one_sided_positive")
        assert 0.0 < neg < 1.0
        assert abs(neg - pos) < 0.001  # symmetric for opposite shifts

    def test_ramp_effect_generator_absolute(self):
        case = _case(effect_abs=50.0, shape="ramp")
        y = case.df[case.df["region"] == TEST_REGION]["kpi"].to_numpy()
        shift = y[N_PRE:] - case.cf[N_PRE:]
        # ramp starts at ~0 effect (only AR(1) noise at t0) and rises ~50
        assert abs(shift[0]) < 8.0
        assert 40.0 < shift[-1] - shift[0] < 60.0

    def test_ramp_effect_generator_relative(self):
        case = _case(effect_pct=10.0, shape="ramp")
        y = case.df[case.df["region"] == TEST_REGION]["kpi"].to_numpy()
        rel = (y[N_PRE:] - case.cf[N_PRE:]) / case.cf[N_PRE:]
        # relative ramp rises from ~0 to ~10% across the window
        assert abs(rel[0]) < 0.05
        assert 0.05 < rel[-1] - rel[0] < 0.18

    def test_shift_does_not_censor_by_realised_draw_sign(self):
        # A non-positive INDIVIDUAL null draw must NOT be censored to NaN --
        # only a non-positive BASELINE (cf_test_sum) makes the relative shift
        # undefined, and that is a caller-level block (see service.py),
        # never a per-draw decision made from the realised simulated value.
        null = np.full(10, -5.0)  # non-positive null totals, positive baseline
        alt, fail = _shift(null, 60.0, 1.0, "relative", 3, "one_sided_positive")
        assert not np.isnan(alt).any()
        assert fail == 0
        assert np.allclose(alt, -5.0 + 60.0 * 0.01)

    def test_shift_relative_is_deterministic_constant_shift(self):
        null = np.array([10.0, -20.0, 35.0, 0.0])
        alt, fail = _shift(null, 200.0, 5.0, "relative", 3, "one_sided_positive")
        expected_shift = 200.0 * (5.0 / 100.0)
        assert np.allclose(alt, null + expected_shift)
        assert fail == 0

    def test_shift_relative_negative_side_flips_direction(self):
        null = np.array([10.0, -20.0, 35.0])
        alt, _ = _shift(null, 200.0, 5.0, "relative", 3, "one_sided_negative")
        expected_shift = -200.0 * (5.0 / 100.0)
        assert np.allclose(alt, null + expected_shift)

    def test_clopper_pearson_zero_sample(self):
        lo, hi = clopper_pearson(0, 0, 0.05)
        assert np.isnan(lo) and np.isnan(hi)


# ---------------------------------------------------------------------------
# Alignment branch coverage
# ---------------------------------------------------------------------------
class TestAlignmentBranches:
    def test_missing_test_region_yields_empty_test(self):
        case = _case()
        test, controls, diag = build_date_keyed_matrix(case.df, ("NOPE",), ("C1", "C2"))
        assert test.isna().all()
        assert diag["dates_retained"] == 0

    def test_single_test_region(self):
        case = _case()
        test, controls, diag = build_date_keyed_matrix(case.df, ("T",), ("C1", "C2"))
        assert test.notna().all()
        assert len(test) == N_PRE + N_TEST

    def test_missing_control_region_column(self):
        case = _case()
        test, controls, diag = build_date_keyed_matrix(case.df, ("T",), ("C1", "NOPE"))
        assert "NOPE" in controls.columns
        assert controls["NOPE"].isna().all()
        assert diag["controls_with_missing_dates"]["NOPE"] == len(controls)

    def test_expected_dates_param(self):
        case = _case()
        all_dates = sorted(case.df["date"].unique())
        expected = list(all_dates[:5])
        test, controls, diag = build_date_keyed_matrix(
            case.df, ("T",), ("C1",), expected_dates=expected
        )
        assert len(test) == 5
        assert diag["dates_expected"] == 5

    def test_single_date_continuity(self):
        case = _case()
        d0 = case.df["date"].unique()[0]
        test, controls, diag = build_date_keyed_matrix(
            case.df, ("T",), ("C1",), expected_dates=[d0]
        )
        assert diag["continuity"] == "single_date"

    def test_non_increasing_continuity(self):
        case = _case()
        d0 = case.df["date"].unique()[0]
        test, controls, diag = build_date_keyed_matrix(
            case.df, ("T",), ("C1",), expected_dates=[d0, d0]
        )
        assert diag["continuity"] == "non_increasing"

    def test_gap_continuity(self):
        case = _case()
        uniq = case.df["date"].unique()
        dates = [uniq[0], uniq[1], uniq[2], uniq[5]]  # skip two weeks
        test, controls, diag = build_date_keyed_matrix(
            case.df, ("T",), ("C1",), expected_dates=dates
        )
        assert diag["continuity"].startswith("1 gap")


# ---------------------------------------------------------------------------
# Fit-comparison branch coverage
# ---------------------------------------------------------------------------
class TestFitComparisonBranches:
    def test_unknown_scenario_rejected(self):
        with pytest.raises(ValueError, match="unknown fit scenario"):
            build_fit_scenario("bogus")

    def test_all_registered_scenarios_buildable_and_comparable(self):
        for name in CONTROLLED_FIT_SCENARIOS:
            case, test_regions, fit_controls = build_fit_scenario(name, seed=0)
            out = compare_fit_methods(case, test_regions, fit_controls, scenario=name, n_sim=100)
            assert len(out["results"]) == 3
            for r in out["results"]:
                assert np.isfinite(r["cf_sum_error_pct"])

    def test_misspecification_scenarios_registered(self):
        expected = {
            "irrelevant_controls",
            "nonlinear_relation",
            "time_varying_coefficients",
            "trend_seasonal_misspecification",
            "measurement_noise",
            "structural_breaks",
            "signal_to_noise_shifts",
        }
        assert expected <= set(CONTROLLED_FIT_SCENARIOS)

    def test_misspecification_error_exceeds_baseline(self):
        # A misspecified counterfactual (here: an independent trend/seasonal
        # component no control spans) must produce a materially larger
        # counterfactual error than the correctly specified baseline for
        # every fit method -- confirming the scenario actually stresses the
        # linear fit rather than being a no-op.
        base_case, base_regions, base_controls = build_fit_scenario("baseline", seed=0)
        base_out = compare_fit_methods(
            base_case, base_regions, base_controls, scenario="baseline", n_sim=200
        )
        mis_case, mis_regions, mis_controls = build_fit_scenario(
            "trend_seasonal_misspecification", seed=0
        )
        mis_out = compare_fit_methods(
            mis_case,
            mis_regions,
            mis_controls,
            scenario="trend_seasonal_misspecification",
            n_sim=200,
        )
        for base_r, mis_r in zip(base_out["results"], mis_out["results"], strict=True):
            assert abs(mis_r["cf_sum_error_pct"]) > abs(base_r["cf_sum_error_pct"])

    def test_irrelevant_controls_included_alongside_real_ones(self):
        case, test_regions, fit_controls = build_fit_scenario("irrelevant_controls", seed=0)
        assert set(fit_controls) == {"C1", "C2", "J1", "J2", "J3"}


# ---------------------------------------------------------------------------
# Fit-policy alignment with validation (Stage 4): elastic_net/lasso now use
# geotestlab.validation.regularisation.build_regularized_model (TimeSeriesSplit
# CV when history allows, exploratory fixed-alpha fallback otherwise) on
# StandardScaler-scaled controls, instead of a silently fixed alpha=0.1.
# ---------------------------------------------------------------------------
class TestFitPolicyAlignment:
    def _pre_df(self, df, n_pre=N_PRE):
        return df[df["date"] < df["date"].unique()[n_pre]]

    def test_elastic_net_uses_cross_validation_with_enough_history(self):
        case = _case()
        fit = fit_counterfactual(
            self._pre_df(case.df), ("T",), ("C1", "C2"), fit_method="elastic_net"
        )
        assert fit.fit_status == "ok"
        assert fit.diagnostics["used_cv"] is True
        assert fit.diagnostics["cv_folds"] is not None and fit.diagnostics["cv_folds"] >= 2
        assert fit.diagnostics["selected_alpha"] is not None
        assert fit.diagnostics["selected_l1_ratio"] is not None
        assert "matches the production evaluation" in fit.diagnostics["evaluation_alignment"]

    def test_lasso_uses_cross_validation_with_enough_history(self):
        case = _case()
        fit = fit_counterfactual(self._pre_df(case.df), ("T",), ("C1", "C2"), fit_method="lasso")
        assert fit.fit_status == "ok"
        assert fit.diagnostics["used_cv"] is True
        assert fit.diagnostics["selected_l1_ratio"] == pytest.approx(1.0)

    def test_elastic_net_short_history_uses_exploratory_fallback(self):
        # Below geotestlab.validation.regularisation.safe_tscv's minimum (6
        # periods), the SAME exploratory fixed-alpha fallback the app itself
        # uses and labels as not cross-validated.
        case = generate_synthetic_case(
            n_pre=5,
            n_test=N_TEST,
            rho=RHO,
            sigma=SIGMA,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=0,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        fit = fit_counterfactual(
            case.df[case.df["date"] < case.df["date"].unique()[5]],
            ("T",),
            ("C1", "C2"),
            fit_method="elastic_net",
        )
        assert fit.diagnostics["used_cv"] is False
        assert "exploratory" in fit.diagnostics["evaluation_alignment"]
        assert "not cross-validated" in fit.diagnostics["evaluation_alignment"].lower()

    def test_ols_labelled_as_not_the_production_evaluation_path(self):
        case = _case()
        fit = fit_counterfactual(self._pre_df(case.df), ("T",), ("C1", "C2"), fit_method="ols")
        assert fit.diagnostics["used_cv"] is False
        assert "NOT the production evaluation" in fit.diagnostics["evaluation_alignment"]
        assert fit.diagnostics["selected_alpha"] is None

    def test_scaler_recorded_and_used_at_projection(self):
        case = _case()
        pre_df = self._pre_df(case.df)
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        fit = fit_counterfactual(pre_df, ("T",), ("C1", "C2"), fit_method="elastic_net")
        assert fit.scaler is not None
        projected, retained_dates, _ = project_counterfactual(fit, test_df, ("T",), ("C1", "C2"))
        assert len(projected) == len(retained_dates) == N_TEST
        assert np.all(np.isfinite(projected))

    def test_ols_and_fallback_have_no_scaler(self):
        case = _case()
        fit_ols = fit_counterfactual(self._pre_df(case.df), ("T",), ("C1", "C2"), fit_method="ols")
        assert fit_ols.scaler is None


# ---------------------------------------------------------------------------
# Bounded Bayesian comparison (Stage 4, item 7): evidence only, never
# auto-selected. Real PyMC sampling (tiny profile) -> slow-marked, like the
# existing Bayesian reduced-sampling smoke test.
# ---------------------------------------------------------------------------
class TestBoundedBayesianEvidence:
    @pytest.mark.slow
    def test_bayesian_comparison_completes_and_is_labelled_evidence_only(self):
        case, test_regions, controls = build_fit_scenario("baseline", seed=0)
        out = compare_bayesian_evidence(case, test_regions, controls, seed=42)
        assert out["fit_method"] == "bayesian"
        assert out["completed"] is True
        assert np.isfinite(out["cf_sum_error_pct"])
        assert out["n_divergences"] == 0
        assert "evidence-only" in out["note"]
        assert "not auto-selected" in out["note"].lower()

    @pytest.mark.slow
    def test_bayesian_sampling_profile_is_bounded(self):
        from geotestlab.power.fit_comparison import (
            BAYESIAN_EVIDENCE_CHAINS,
            BAYESIAN_EVIDENCE_DRAWS,
            BAYESIAN_EVIDENCE_TUNE,
        )

        # Deliberately tiny -- never the production MCMC profile
        # (BayesianConfig defaults to draws=2000/tune=1000/chains=4).
        assert BAYESIAN_EVIDENCE_DRAWS <= 50
        assert BAYESIAN_EVIDENCE_TUNE <= 50
        assert BAYESIAN_EVIDENCE_CHAINS == 1


# ---------------------------------------------------------------------------
# Fixed test-region composition (defect 3): a date where SOME but not all
# selected test regions report must never be silently summed as if the
# missing region contributed zero -- it must be excluded, with the missing
# region(s) recorded.
# ---------------------------------------------------------------------------
class TestFixedTestRegionComposition:
    def _two_test_region_df(self):
        case = _case()
        df = case.df.copy()
        t = df[df["region"] == TEST_REGION].copy()
        t2 = t.copy()
        t2["region"] = "T2"
        t2["kpi"] = t2["kpi"] + 7.0
        return pd.concat([df, t2], ignore_index=True)

    def test_partial_test_region_presence_excludes_date(self):
        df = self._two_test_region_df()
        t2_mask = df["region"] == "T2"
        drop_dates = list(sorted(df.loc[t2_mask, "date"].unique())[:3])
        df = df[~(t2_mask & df["date"].isin(drop_dates))]
        test, controls, diag = build_date_keyed_matrix(df, ("T", "T2"), ("C1", "C2"))
        assert test.isna().sum() == 3
        for d in drop_dates:
            assert pd.isna(test.loc[pd.Timestamp(d)])
        for d in drop_dates:
            assert diag["missing_test_regions_by_date"][str(pd.Timestamp(d).date())] == ["T2"]

    def test_partial_presence_never_sums_available_subset(self):
        # Explicitly guard against the OLD behavior (min_count=1): a date
        # where T2 is missing must NOT equal T's own value that date (which
        # is what a silent "sum whichever is available" would produce).
        df = self._two_test_region_df()
        t2_mask = df["region"] == "T2"
        one_date = sorted(df.loc[df["region"] == "T", "date"].unique())[50]
        df = df[~(t2_mask & (df["date"] == one_date))]
        test, controls, diag = build_date_keyed_matrix(df, ("T", "T2"), ("C1", "C2"))
        assert pd.isna(test.loc[pd.Timestamp(one_date)])

    def test_multiple_test_regions_different_missing_dates_reduce_effective_periods(self):
        df = self._two_test_region_df()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        drop_t, drop_t2 = test_dates[0], test_dates[1]
        df = df[~((df["region"] == "T") & (df["date"] == drop_t))]
        df = df[~((df["region"] == "T2") & (df["date"] == drop_t2))]
        pre_df = df[df["date"] < test_dates[0]]
        test_df = df[df["date"].isin(test_dates)]
        _, _, meta = model_simulation(pre_df, test_df, ("T", "T2"), ("C1", "C2"), N_TEST, 500, 3)
        assert meta["effective_test_periods"] == N_TEST - 2
        assert meta["requested_test_periods"] == N_TEST


# ---------------------------------------------------------------------------
# One authoritative aligned test window (defect 1): the counterfactual
# projection, the AR(1)/bootstrap noise horizon and the reported effective
# duration must all come from the SAME jointly-complete (test AND every
# control present) date set.
# ---------------------------------------------------------------------------
class TestAlignedTestWindow:
    def test_missing_control_date_in_test_window_reduces_effective_periods(self):
        # The test region itself is present on every test date; only a
        # CONTROL is missing on one date. The old code derived the AR(1)
        # horizon from test-only availability, so this case used to leave
        # the horizon at N_TEST while the counterfactual projection silently
        # dropped a row -- a mismatch. It must now reduce together.
        case = _case()
        df = case.df.copy()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        missing_date = test_dates[2]
        df = df[~((df["region"] == "C1") & (df["date"] == missing_date))]
        pre_df = df[df["date"] < test_dates[0]]
        test_df = df[df["date"].isin(test_dates)]
        _, _, meta = model_simulation(pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, 3)
        assert meta["effective_test_periods"] == N_TEST - 1
        assert meta["requested_test_periods"] == N_TEST
        reasons = meta["matrix_diagnostics"]["test_window"]["removal_reasons"]
        assert reasons[str(pd.Timestamp(missing_date).date())] == "control_missing:C1"

    def test_control_missing_segment_reduces_effective_periods(self):
        case = _case()
        df = case.df.copy()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        segment = test_dates[2:5]
        df = df[~((df["region"] == "C2") & (df["date"].isin(segment)))]
        pre_df = df[df["date"] < test_dates[0]]
        test_df = df[df["date"].isin(test_dates)]
        _, _, meta = model_simulation(pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, 3)
        assert meta["effective_test_periods"] == N_TEST - len(segment)

    def test_all_test_regions_outage_date_excluded(self):
        case = _case()
        df = case.df.copy()
        t = df[df["region"] == TEST_REGION].copy()
        t2 = t.copy()
        t2["region"] = "T2"
        t2["kpi"] = t2["kpi"] + 7.0
        df = pd.concat([df, t2], ignore_index=True)
        test_dates = sorted(df["date"].unique())[N_PRE:]
        outage_date = test_dates[4]
        df = df[~(df["region"].isin(("T", "T2")) & (df["date"] == outage_date))]
        pre_df = df[df["date"] < test_dates[0]]
        test_df = df[df["date"].isin(test_dates)]
        _, _, meta = model_simulation(pre_df, test_df, ("T", "T2"), ("C1", "C2"), N_TEST, 500, 3)
        assert meta["effective_test_periods"] == N_TEST - 1
        reasons = meta["matrix_diagnostics"]["test_window"]["removal_reasons"]
        assert reasons[str(pd.Timestamp(outage_date).date())] == "test_missing"

    def test_effective_test_periods_reported_end_to_end(self):
        case = _case()
        df = case.df.copy()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        missing_date = test_dates[0]
        df = df[~((df["region"] == "C1") & (df["date"] == missing_date))]
        res = run_power_analysis(df, N_PRE, _config())
        assert res.completed is True
        assert res.effective_test_periods == N_TEST - 1
        assert res.requested_test_periods == N_TEST

    def test_zero_jointly_complete_test_dates_blocks(self):
        # Every test-window date has a missing control -> no jointly
        # complete row exists to project a counterfactual or a horizon over.
        case = _case()
        df = case.df.copy()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        df = df[~((df["region"] == "C1") & (df["date"].isin(test_dates)))]
        res = run_power_analysis(df, N_PRE, _config())
        assert res.completed is False
        assert res.mde is None
        assert any("jointly complete" in b for b in res.blockers)

    def test_residual_simulation_effective_periods_matches_model_simulation(self):
        case = _case()
        df = case.df.copy()
        test_dates = sorted(df["date"].unique())[N_PRE:]
        missing_date = test_dates[3]
        df = df[~((df["region"] == "C2") & (df["date"] == missing_date))]
        res = run_power_analysis(
            df, N_PRE, _config(method="residual_simulation", min_placebo_windows=1)
        )
        assert res.completed is True
        assert res.effective_test_periods == N_TEST - 1


# ---------------------------------------------------------------------------
# Common random numbers (defect 5): reusing one alternative no-effect sample
# across every requested effect via a deterministic shift makes the power
# curve invariant to effect-grid order/density and guarantees one-sided
# monotonicity and grid-density-stable MDE.
# ---------------------------------------------------------------------------
class TestCommonRandomNumbersGrid:
    def test_effect_grid_order_invariance(self):
        case = _case()
        forward = _config(effect_grid=(0.0, 1.0, 2.0, 5.0, 10.0))
        backward = _config(effect_grid=(10.0, 5.0, 2.0, 1.0, 0.0))
        res_fwd = run_power_analysis(case.df, N_PRE, forward)
        res_bwd = run_power_analysis(case.df, N_PRE, backward)
        order_fwd = np.argsort(res_fwd.effect_grid)
        order_bwd = np.argsort(res_bwd.effect_grid)
        assert np.array_equal(res_fwd.power_curve[order_fwd], res_bwd.power_curve[order_bwd])

    def test_sparse_and_dense_grid_agree_at_shared_effect(self):
        case = _case()
        sparse = _config(effect_grid=(0.0, 5.0, 10.0))
        dense = _config(effect_grid=tuple(np.linspace(0.0, 10.0, 21)))
        res_sparse = run_power_analysis(case.df, N_PRE, sparse)
        res_dense = run_power_analysis(case.df, N_PRE, dense)
        i_sparse = int(np.argmin(np.abs(res_sparse.effect_grid - 5.0)))
        i_dense = int(np.argmin(np.abs(res_dense.effect_grid - 5.0)))
        assert res_sparse.power_curve[i_sparse] == res_dense.power_curve[i_dense]

    def test_one_sided_power_monotonic_in_effect(self):
        case = _case()
        res = run_power_analysis(
            case.df, N_PRE, _config(effect_grid=tuple(np.linspace(0.0, 20.0, 15)))
        )
        assert np.all(np.diff(res.power_curve) >= 0.0)

    def test_mde_stable_across_grid_density(self):
        case = _case(effect_pct=8.0)
        dense = _config()
        sparse = _config(effect_grid=(0.0, 10.0, 20.0, 30.0, 40.0, 50.0))
        res_dense = run_power_analysis(case.df, N_PRE, dense)
        res_sparse = run_power_analysis(case.df, N_PRE, sparse)
        assert res_dense.mde_reached and res_sparse.mde_reached
        assert abs(res_dense.mde - res_sparse.mde) <= 1.5

    def test_seed_reproducibility(self):
        case = _case()
        res_a = run_power_analysis(case.df, N_PRE, _config(random_seed=99))
        res_b = run_power_analysis(case.df, N_PRE, _config(random_seed=99))
        assert np.array_equal(res_a.power_curve, res_b.power_curve)
        assert res_a.mde == res_b.mde
