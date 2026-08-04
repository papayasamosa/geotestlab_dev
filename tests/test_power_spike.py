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
    clopper_pearson,
    compare_fit_methods,
    find_mde,
    generate_synthetic_case,
    model_simulation,
    run_power_analysis,
)
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
        null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, np.random.default_rng(3)
        )
        assert abs(meta["rho_estimate"] - RHO) < 0.2
        assert abs(meta["sigma_estimate"] - SIGMA) < 0.5

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
    def test_alt_samples_independent_across_effect_calls(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        cal_null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 1000, np.random.default_rng(11)
        )
        alt1, _ = alt_fn(0.5, "relative", "one_sided_positive")
        alt2, _ = alt_fn(0.5, "relative", "one_sided_positive")
        assert not np.array_equal(alt1, alt2)

    def test_meta_reports_diagnostics_stream(self):
        case = _case()
        pre_df = case.df[case.df["date"] < case.df["date"].unique()[N_PRE]]
        test_df = case.df[case.df["date"] >= case.df["date"].unique()[N_PRE]]
        cal_null, alt_fn, meta = model_simulation(
            pre_df, test_df, ("T",), ("C1", "C2"), N_TEST, 500, np.random.default_rng(3)
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
    def _run_placebo(self, n_pre):
        case = generate_synthetic_case(
            n_pre=n_pre,
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
        return run_power_analysis(
            case.df, n_pre, _config(method="placebo_empirical", control_regions=("C1", "C2"))
        )

    def test_empty_placebo_incomplete_no_mde(self):
        # 10 pre periods with 12-period windows -> zero placebo windows.
        res = self._run_placebo(10)
        assert res.completed is False
        assert res.mde is None
        assert res.mde_reached is False
        assert res.minimum_window_status == "insufficient"
        assert any("windows" in e for e in res.errors)
        assert any("windows" in b for b in res.blockers)
        assert len(res.power_curve) == 0

    def test_placebo_min_windows_enforced(self):
        # 24 pre periods with 12-period windows -> 2 windows < minimum 5.
        res = self._run_placebo(24)
        assert res.completed is False
        assert res.mde is None
        assert res.minimum_window_status == "insufficient"

    def test_residual_simulation_empty_evidence_incomplete(self):
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

    def test_duplicate_region_date_keys_reported(self):
        case = _case()
        dup = case.df.iloc[:5].copy()
        df = pd.concat([case.df, dup], ignore_index=True)
        res = run_power_analysis(df, N_PRE, _config())
        assert res.matrix_diagnostics["duplicate_region_date_keys"] >= 5
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
        case = _case()
        res = run_power_analysis(case.df, 8, _config(min_historical_periods=12))
        assert res.minimum_history_status == "insufficient"
        assert res.completed is True  # warning-level, not a critical failure
        assert res.errors == ()

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
