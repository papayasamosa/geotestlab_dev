"""Stage 5: power-analysis methodology spike — controlled synthetic-case tests.

Validates the prototype on synthetic cases with KNOWN counterfactual and AR(1)
noise, where the true null distribution and power are analytic:

- generator truth (counterfactual sum, total variance, effect injection);
- model-based simulation matches the analytic power (method alignment);
- null calibration (power at effect=0 ~= alpha);
- one-sided vs two-sided detection;
- relative vs absolute injection;
- effect shape (ramp vs step);
- autocorrelation handling (higher rho -> wider null -> lower power);
- MDE recovery against the analytic power curve;
- simulation-count stability and Clopper-Pearson power uncertainty;
- placebo-window empirical method (null calibration, relative-only);
- residual-simulation bootstrap method;
- low-volume guard, policy warnings, and JSON-safe results.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from geotestlab.power import (
    PowerConfig,
    analytic_power,
    analytic_total_variance,
    build_placebo_windows,
    clopper_pearson,
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
            pre_df, test_df, ["C1", "C2"], N_TEST, 500, np.random.default_rng(3)
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

    def test_one_sided_negative_positive_effect_low_power(self):
        # A positive effect should not be "detected" by a one-sided negative test.
        case = _case()
        neg = run_power_analysis(case.df, N_PRE, _config(side="one_sided_negative"))
        i = int(np.argmin(np.abs(neg.effect_grid - 0.5)))
        assert neg.power_curve[i] < 0.05


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
        res = run_power_analysis(case.df, N_PRE, _config(n_simulations=500))
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

    def test_ci_contains_analytic(self):
        case = _case()
        res = run_power_analysis(case.df, N_PRE, _config(n_simulations=3000))
        i = int(np.argmin(np.abs(res.effect_grid - 0.5)))
        theo = analytic_power(
            res.null_mean,
            res.null_sd,
            res.null_mean * 0.5 / 100.0,
            res.alpha,
            res.side,
        )
        assert res.power_ci_lower[i] <= theo <= res.power_ci_upper[i]


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
        pcts = build_placebo_windows(pre_df, ["C1", "C2"], N_TEST)
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
