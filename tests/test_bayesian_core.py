"""Direct deterministic unit tests for the extracted Bayesian core (Stage 3).

Covers, with small hand-calculable fixtures (not AppTest, no production
sampling profile):
- prior parameter construction (standard + structurally informed, with/without lag);
- model feature construction (combined matrix, lags, period splits, guards);
- AR(1) gap steps;
- AR(1) residual simulation (deterministic with a seeded RNG);
- fitted-mean intervals;
- posterior predictive intervals;
- uplift aggregation;
- diagnostic summarisation;
- serialisable posterior summaries (trace kept separate);
- PyMC model construction (no sampling) and posterior extraction;
- the pure service end-to-end with an injected fake builder/sampler.

The PyMC trace is never sampled with the production profile in this file; the
only PyMC usage is model construction (deterministic, no sampling).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from geotestlab.bayesian import (
    BayesianConfig,
    BayesianResult,
    InsufficientPrePeriodError,
    MissingTestPeriodError,
    ar1_gap_steps,
    build_bayesian_model,
    build_bayesian_model_data,
    build_prior_spec,
    calculate_structural_prior_sigmas,
    compute_correlation_sigma_bounds,
    compute_fitted_mean_intervals,
    compute_predictive_interval,
    compute_uplift_aggregation,
    extract_posterior,
    run_bayesian,
    simulate_ar1_predictive_residuals,
    summarize_mcmc_diagnostics,
)
from geotestlab.validation import get_frequency_config

WEEKLY = get_frequency_config("weekly")
DAILY = get_frequency_config("daily")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _validation_agg(dates, test_vals, control_map):
    """Validation-style long dataframe: columns date, region, kpi."""
    rows = []
    for d, v in zip(dates, test_vals):
        rows.append({"date": d, "region": "T", "kpi": float(v)})
    for region, values in control_map.items():
        for d, v in zip(dates, values):
            rows.append({"date": d, "region": region, "kpi": float(v)})
    return pd.DataFrame(rows)


def _structural_agg(regions, features, populations, values):
    """Region-level structural dataframe: geo_col, Population, feature columns."""
    geo_col = "region"
    rows = []
    for r in regions:
        row = {geo_col: r, "Population": float(populations[r])}
        for f, v in zip(features, values[r]):
            row[f] = float(v)
        rows.append(row)
    return pd.DataFrame(rows)


def _weekly_agg(n_pre=12, n_test=4, gap_index=None):
    """Weekly validation aggregate: T + C1 + C2 over pre+test weeks."""
    dates = pd.date_range("2025-01-06", periods=n_pre + n_test, freq="7D")
    pre = np.arange(1, n_pre + 1, dtype=float)
    test = np.arange(101, 101 + n_test, dtype=float)
    test_vals = list(pre) + list(test)
    # Controls track the test KPI with small offsets (no NaNs unless gap_index).
    c1 = [v + 2 for v in test_vals]
    c2 = [v * 0.9 + 5 for v in test_vals]
    if gap_index is not None:
        c1[gap_index] = np.nan
    return _validation_agg(dates, test_vals, {"C1": c1, "C2": c2}), dates


# ---------------------------------------------------------------------------
# AR(1) gap steps
# ---------------------------------------------------------------------------
class TestAr1GapSteps:
    def test_weekly_contiguous(self):
        assert ar1_gap_steps("2025-01-06", "2025-01-13", WEEKLY) == 1

    def test_weekly_two_weeks(self):
        assert ar1_gap_steps("2025-01-06", "2025-01-20", WEEKLY) == 2

    def test_daily_seven_days(self):
        assert ar1_gap_steps("2025-01-06", "2025-01-13", DAILY) == 7

    def test_min_one_when_no_gap(self):
        assert ar1_gap_steps("2025-01-06", "2025-01-06", WEEKLY) == 1

    def test_invalid_dates_fall_back_to_one(self):
        assert ar1_gap_steps(None, None, WEEKLY) == 1


# ---------------------------------------------------------------------------
# AR(1) residual simulation
# ---------------------------------------------------------------------------
class TestAr1Simulation:
    def test_shape_and_reproducibility(self):
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        rho = np.array([0.5, 0.2])
        sigma = np.array([1.0, 2.0])
        a = simulate_ar1_predictive_residuals(rho, sigma, 5, rng1)
        b = simulate_ar1_predictive_residuals(rho, sigma, 5, rng2)
        assert a.shape == (2, 5)
        np.testing.assert_array_equal(a, b)

    def test_rho_zero_is_idd_and_ignores_e_start(self):
        rho = np.zeros(1000)
        sigma = np.ones(1000) * 2.0
        e_a = np.zeros(1000)
        e_b = np.ones(1000) * 99.0
        a = simulate_ar1_predictive_residuals(rho, sigma, 1, np.random.default_rng(7), e_start=e_a)
        b = simulate_ar1_predictive_residuals(rho, sigma, 1, np.random.default_rng(7), e_start=e_b)
        np.testing.assert_array_equal(a, b)
        # i.i.d. Normal(0, sigma): empirical mean ~ 0, sd ~ sigma
        assert abs(a.mean()) < 0.2
        assert abs(a.std() - 2.0) < 0.15

    def test_rho_half_first_step_is_rho_times_e_start_plus_noise(self):
        # First step: 0.5*1.0 + noise. Empirically (many draws) mean ~ 0.5.
        many = simulate_ar1_predictive_residuals(
            np.full(20000, 0.5), np.ones(20000), 1, np.random.default_rng(3), e_start=np.ones(20000)
        )
        assert abs(many[:, 0].mean() - 0.5) < 0.02

    def test_gap_steps_add_warmup(self):
        rng1 = np.random.default_rng(11)
        rng2 = np.random.default_rng(11)
        rho = np.array([0.5])
        sigma = np.array([1.0])
        e_start = np.array([2.0])
        contig = simulate_ar1_predictive_residuals(
            rho, sigma, 1, rng1, e_start=e_start, n_gap_steps=1
        )
        gap = simulate_ar1_predictive_residuals(rho, sigma, 1, rng2, e_start=e_start, n_gap_steps=3)
        # A gap of 3 simulates 2 warm-up steps, so the first forecast differs.
        assert not np.allclose(contig, gap)


# ---------------------------------------------------------------------------
# Prior parameter construction
# ---------------------------------------------------------------------------
class TestCorrelationSigmaBounds:
    def test_high_correlation_bounds(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        X = np.column_stack([y, -y])
        mn, mx = compute_correlation_sigma_bounds(X, y)
        # median abs corr = 1.0 -> clipped to 0.95
        assert mn == pytest.approx(0.38)
        assert mx == pytest.approx(0.9)

    def test_zero_correlation_low_bounds(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])
        X = np.ones((4, 1)) * 5.0  # zero variance -> corr 0 -> clipped floor
        mn, mx = compute_correlation_sigma_bounds(X, y)
        assert mn == pytest.approx(0.10)
        assert mx == pytest.approx(0.30)

    def test_empty_input_falls_back(self):
        mn, mx = compute_correlation_sigma_bounds(np.empty((0, 2)), np.empty(0))
        assert (mn, mx) == (0.25, 0.70)


class TestStructuralPriorSigmas:
    def test_no_valid_features_uniform_weak(self):
        agg = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [1.0], "C1": [2.0], "C2": [3.0]},
        )
        sigmas, df = calculate_structural_prior_sigmas(
            agg, ["T"], ["C1", "C2"], "region", ["missing_col", "also_missing"]
        )
        np.testing.assert_allclose(sigmas, [0.5, 0.5])
        assert (df["Prior Type"] == "Standard weak prior").all()

    def test_single_control_uniform(self):
        agg = _structural_agg(["T", "C1"], ["f1"], {"T": 10, "C1": 10}, {"T": [1.0], "C1": [2.0]})
        sigmas, df = calculate_structural_prior_sigmas(agg, ["T"], ["C1"], "region", ["f1"])
        np.testing.assert_allclose(sigmas, [0.5])

    def test_identical_similarities_uniform(self):
        agg = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [1.0], "C1": [1.0], "C2": [1.0]},
        )
        sigmas, _ = calculate_structural_prior_sigmas(agg, ["T"], ["C1", "C2"], "region", ["f1"])
        np.testing.assert_allclose(sigmas, [0.5, 0.5])

    def test_closer_control_gets_wider_sigma(self):
        agg = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [0.0], "C1": [1.0], "C2": [100.0]},
        )
        sigmas, df = calculate_structural_prior_sigmas(
            agg, ["T"], ["C1", "C2"], "region", ["f1"], min_sigma=0.25, max_sigma=0.70
        )
        assert sigmas[0] > sigmas[1]
        assert (sigmas >= 0.25).all() and (sigmas <= 0.70).all()
        assert (df["Prior Type"] == "Structurally informed").all()


class TestBuildPriorSpec:
    def test_standard_no_lag(self):
        spec = build_prior_spec(
            ["C1", "C2"],
            ["C1", "C2"],
            ["f1"],
            False,
            1,
            WEEKLY,
            False,
            pd.DataFrame(),
            ["T"],
            "region",
        )
        np.testing.assert_allclose(spec.prior_sigmas, [0.5, 0.5])
        assert spec.prior_style == "Standard weak prior"
        assert list(spec.structural_prior_df["Control Region"]) == ["C1", "C2"]
        assert spec.min_sigma == 0.25 and spec.max_sigma == 0.70

    def test_standard_with_lag(self):
        spec = build_prior_spec(
            ["C1", "C2"],
            ["C1", "C2", "C1_lag1", "C2_lag1"],
            ["f1"],
            True,
            1,
            WEEKLY,
            False,
            pd.DataFrame(),
            ["T"],
            "region",
        )
        assert len(spec.prior_sigmas) == 4
        np.testing.assert_allclose(spec.prior_sigmas, [0.5] * 4)
        df = spec.structural_prior_df
        assert "Feature" in df.columns and "Term Type" in df.columns
        assert len(df) == 4
        assert list(df["Feature"]) == ["C1", "C2", "C1_lag1", "C2_lag1"]

    def test_structural_no_lag(self):
        agg = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [0.0], "C1": [1.0], "C2": [100.0]},
        )
        y = np.array([1.0, 2.0, 3.0, 4.0])
        X = np.column_stack([y, y])
        spec = build_prior_spec(
            ["C1", "C2"],
            ["C1", "C2"],
            ["f1"],
            False,
            1,
            WEEKLY,
            True,
            agg,
            ["T"],
            "region",
            X_pre=X,
            y_pre=y,
        )
        assert spec.prior_style == "Structurally informed"
        assert spec.min_sigma == pytest.approx(0.38)
        assert spec.max_sigma == pytest.approx(0.9)
        assert (spec.prior_sigmas >= 0.25).all()

    def test_structural_with_lag_duplicates_sigmas(self):
        agg = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [0.0], "C1": [1.0], "C2": [100.0]},
        )
        y = np.array([1.0, 2.0, 3.0, 4.0])
        X = np.column_stack([y, y])
        spec = build_prior_spec(
            ["C1", "C2"],
            ["C1", "C2", "C1_lag1", "C2_lag1"],
            ["f1"],
            True,
            1,
            WEEKLY,
            True,
            agg,
            ["T"],
            "region",
            X_pre=X,
            y_pre=y,
        )
        assert len(spec.prior_sigmas) == 4
        # Each control's lagged term reuses the same structural sigma.
        np.testing.assert_allclose(spec.prior_sigmas[:2], spec.prior_sigmas[2:])
        df = spec.structural_prior_df
        assert len(df) == 4


# ---------------------------------------------------------------------------
# Model feature construction
# ---------------------------------------------------------------------------
class TestBuildModelData:
    def test_no_lag_splits_and_scaling(self):
        agg, dates = _weekly_agg()
        data = build_bayesian_model_data(
            agg,
            ["C1", "C2"],
            ["T"],
            WEEKLY,
            False,
            1,
            dates[0],
            dates[11],
            dates[12],
            dates[15],
            False,
            None,
            None,
        )
        assert data.feature_cols == ("C1", "C2")
        assert data.X_pre.shape == (12, 2)
        assert data.y_pre.shape == (12,)
        assert data.X_test.shape == (4, 2)
        assert data.y_test_actual.shape == (4,)
        assert data.post_dates is None and data.X_post is None
        # StandardScaler: zero mean / unit variance
        np.testing.assert_allclose(data.X_pre.mean(axis=0), 0.0, atol=1e-10)
        np.testing.assert_allclose(data.X_pre.std(axis=0), 1.0, atol=1e-10)
        # y_pre is original; inverse of scaled reproduces it
        np.testing.assert_allclose(
            data.scaler_y.inverse_transform(data.y_pre_scaled.reshape(-1, 1)).flatten(), data.y_pre
        )

    def test_with_lag_feature_cols_and_metadata(self):
        agg, dates = _weekly_agg()
        data = build_bayesian_model_data(
            agg,
            ["C1", "C2"],
            ["T"],
            WEEKLY,
            True,
            1,
            dates[0],
            dates[11],
            dates[12],
            dates[15],
            False,
            None,
            None,
        )
        assert data.feature_cols == ("C1", "C2", "C1_lag1", "C2_lag1")
        assert data.lag_drop_metadata is not None
        assert "lag_drop_pct" in data.lag_drop_metadata
        assert data.X_pre.shape[1] == 4

    def test_insufficient_pre_raises(self):
        agg, dates = _weekly_agg(n_pre=3, n_test=4)
        with pytest.raises(InsufficientPrePeriodError):
            build_bayesian_model_data(
                agg,
                ["C1", "C2"],
                ["T"],
                WEEKLY,
                False,
                1,
                dates[0],
                dates[2],
                dates[3],
                dates[6],
                False,
                None,
                None,
            )

    def test_empty_test_raises(self):
        agg, dates = _weekly_agg()
        # Test window entirely after the data ends.
        with pytest.raises(MissingTestPeriodError):
            build_bayesian_model_data(
                agg,
                ["C1", "C2"],
                ["T"],
                WEEKLY,
                False,
                1,
                dates[0],
                dates[15],
                pd.Timestamp("2030-01-01"),
                pd.Timestamp("2030-02-01"),
                False,
                None,
                None,
            )

    def test_post_period(self):
        dates = pd.date_range("2025-01-06", periods=20, freq="7D")
        test_vals = list(range(1, 21))
        agg = _validation_agg(
            dates,
            test_vals,
            {"C1": [v + 1 for v in test_vals], "C2": [v * 0.9 + 5 for v in test_vals]},
        )
        data = build_bayesian_model_data(
            agg,
            ["C1", "C2"],
            ["T"],
            WEEKLY,
            False,
            1,
            dates[0],
            dates[11],
            dates[12],
            dates[15],
            True,
            dates[16],
            dates[19],
        )
        assert data.post_dates is not None and len(data.post_dates) == 4
        assert data.X_post.shape == (4, 2)


# ---------------------------------------------------------------------------
# Fitted-mean intervals
# ---------------------------------------------------------------------------
class TestFittedMeanIntervals:
    def test_hand_calculable(self):
        scaler_y = StandardScaler()
        scaler_y.fit(np.array([[10.0], [20.0]]))
        post_int = np.array([1.0])
        post_coeff = np.array([[2.0, -1.0]])
        X_scaled = np.array([[1.0, 1.0], [2.0, 0.0]])
        mu_scaled, mu_orig, mean, lo, hi = compute_fitted_mean_intervals(
            post_int, post_coeff, X_scaled, scaler_y
        )
        # mu_scaled = [1 + 2 - 1, 1 + 4 - 0] = [2, 5]
        np.testing.assert_allclose(mu_scaled, [[2.0, 5.0]])
        expected = scaler_y.inverse_transform(np.array([[2.0], [5.0]])).flatten()
        np.testing.assert_allclose(mu_orig, [expected])
        # Single draw: mean == the draw, HDI collapses to the draw.
        np.testing.assert_allclose(mean, expected)
        np.testing.assert_allclose(lo, expected)
        np.testing.assert_allclose(hi, expected)

    def test_multiple_draws_percentiles(self):
        scaler_y = StandardScaler()
        scaler_y.fit(np.array([[0.0], [10.0]]))
        post_int = np.array([0.0, 10.0])
        post_coeff = np.array([[1.0, 1.0], [1.0, 1.0]])
        X_scaled = np.zeros((2, 2))  # 2 periods x 2 features, all zero -> mu = intercept
        _, mu_orig, mean, lo, hi = compute_fitted_mean_intervals(
            post_int, post_coeff, X_scaled, scaler_y
        )
        # mu_scaled = [0, 10] per period; inverse under scaler on [0,10]
        # (mean 5, scale 5 with ddof=0) is [5, 55] per period.
        np.testing.assert_allclose(mu_orig, [[5.0, 5.0], [55.0, 55.0]])
        np.testing.assert_allclose(mean, [30.0, 30.0])
        assert lo[0] <= mean[0] <= hi[0]


# ---------------------------------------------------------------------------
# Posterior predictive intervals
# ---------------------------------------------------------------------------
class TestPredictiveInterval:
    def test_rho_zero_is_deterministic_and_in_original_units(self):
        scaler_y = StandardScaler()
        scaler_y.fit(np.array([[0.0], [1.0]]))
        rng1 = np.random.default_rng(5)
        rng2 = np.random.default_rng(5)
        mu = np.zeros((1, 4))
        a = compute_predictive_interval(np.array([0.0]), np.array([1.0]), mu, scaler_y, rng1)
        b = compute_predictive_interval(np.array([0.0]), np.array([1.0]), mu, scaler_y, rng2)
        assert a[0].shape == (4,) and a[1].shape == (4,)
        assert a[2].shape == (1, 4)
        np.testing.assert_allclose(a[0], b[0])
        np.testing.assert_allclose(a[1], b[1])

    def test_resid_returned_for_post_continuation(self):
        scaler_y = StandardScaler()
        scaler_y.fit(np.array([[0.0], [1.0]]))
        mu = np.zeros((2, 3))
        rng = np.random.default_rng(9)
        _, _, _, resid = compute_predictive_interval(
            np.array([0.5, 0.5]),
            np.array([1.0, 1.0]),
            mu,
            scaler_y,
            rng,
            e_start=np.array([0.0, 0.0]),
        )
        assert resid.shape == (2, 3)


# ---------------------------------------------------------------------------
# Uplift aggregation
# ---------------------------------------------------------------------------
class TestUpliftAggregation:
    def test_hand_calculable(self):
        y_actual = np.array([10.0, 20.0])  # total 30
        total_pred = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
        mu_test = np.array([[8.0], [18.0], [28.0], [38.0], [48.0]])  # sums 8..48
        u = compute_uplift_aggregation(y_actual, total_pred, mu_test)
        np.testing.assert_allclose(u["uplift_samples"], [20, 10, 0, -10, -20])
        assert u["prob_pos"] == pytest.approx(0.4)
        assert u["mean_uplift"] == pytest.approx(0.0)
        assert u["uplift_pct"] == pytest.approx(0.0)
        # percentile(3) on sorted [-20,-10,0,10,20]: -20 + 0.12*10 = -18.8
        assert u["uplift_pi_lower"] == pytest.approx(-18.8)
        assert u["uplift_pi_upper"] == pytest.approx(18.8)
        # HDI on uplift_mean = 30 - [8,18,28,38,48] = [22,12,2,-8,-18]
        assert u["uplift_hdi_lower"] == pytest.approx(-16.8)
        assert u["uplift_hdi_upper"] == pytest.approx(20.8)

    def test_zero_predicted_total_pct_nan(self):
        y_actual = np.array([5.0])
        total_pred = np.array([0.0, 0.0])
        mu_test = np.zeros((2, 1))
        u = compute_uplift_aggregation(y_actual, total_pred, mu_test)
        assert np.isnan(u["uplift_pct"])


# ---------------------------------------------------------------------------
# Diagnostic summarisation
# ---------------------------------------------------------------------------
class TestMcmcDiagnostics:
    def _summary(self, rhat=1.0, ess=1000.0, mcse=0.01, sd=1.0):
        return pd.DataFrame(
            {
                "r_hat": [rhat],
                "ess_bulk": [ess],
                "ess_tail": [ess],
                "mcse_mean": [mcse],
                "sd": [sd],
            }
        )

    def test_all_pass(self):
        d = summarize_mcmc_diagnostics(self._summary())
        assert d["overall_ok"] is True
        assert d["status"] == "✅ Good"
        assert d["messages"] == []
        assert d["divergence_ok"] is True

    def test_rhat_fails(self):
        d = summarize_mcmc_diagnostics(self._summary(rhat=1.02))
        assert d["rhat_ok"] is False
        assert d["overall_ok"] is False
        assert any("R‑hat" in m for m in d["messages"])

    def test_ess_fails_below_threshold(self):
        d = summarize_mcmc_diagnostics(self._summary(ess=100), ess_min_threshold=500)
        assert d["ess_ok"] is False
        assert any("Effective sample size" in m for m in d["messages"])

    def test_mcse_fails(self):
        d = summarize_mcmc_diagnostics(self._summary(mcse=0.15, sd=1.0))
        assert d["mcse_ok"] is False
        assert any("MCSE/SD" in m for m in d["messages"])

    def test_divergences_fail_with_rate(self):
        d = summarize_mcmc_diagnostics(self._summary(), n_divergences=2, n_total_draws=100)
        assert d["divergence_ok"] is False
        assert d["divergence_rate"] == pytest.approx(0.02)
        assert d["overall_ok"] is False
        assert any("divergent" in m for m in d["messages"])

    def test_divergences_none_skips(self):
        d = summarize_mcmc_diagnostics(self._summary(), n_divergences=None)
        assert d["divergence_ok"] is True


# ---------------------------------------------------------------------------
# Serialisable posterior summaries
# ---------------------------------------------------------------------------
class TestSerialisableSummaries:
    def test_to_dict_excludes_trace_and_keeps_legacy_keys(self):
        res = BayesianResult(
            completed=True,
            pre_dates=np.array([1, 2]),
            y_pre=np.array([1.0, 2.0]),
            uplift_samples=np.array([1.0]),
            control_list=("C1", "C2"),
            base_control_list=("C1", "C2"),
            model_feature_cols=("C1", "C2"),
            frequency_config=WEEKLY,
            trace=object(),
        )
        d = res.to_dict()
        assert "trace" not in d
        assert d["pre_dates"] is res.pre_dates
        assert d["control_list"] == ["C1", "C2"]
        assert d["model_feature_cols"] == ["C1", "C2"]
        assert d["frequency_config"] is WEEKLY
        assert "uplift_samples" in d

    def test_non_completed_result_to_dict(self):
        res = BayesianResult(completed=False, errors=("boom",))
        d = res.to_dict()
        assert res.completed is False
        assert "trace" not in d
        assert d["pre_dates"] is None


# ---------------------------------------------------------------------------
# PyMC model construction (no sampling) + posterior extraction
# ---------------------------------------------------------------------------
class TestModelConstruction:
    def test_ar1_model_has_rho(self):
        X = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.5]])
        y = np.array([0.1, 0.2, 0.3, 0.4])
        model = build_bayesian_model(X, y, np.array([0.5, 0.5]), use_ar1_errors=True)
        names = set(model.named_vars.keys())
        assert {"intercept", "coeffs", "sigma", "rho", "y_obs", "y_obs_first"} <= names

    def test_no_ar1_model_has_no_rho(self):
        X = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.5]])
        y = np.array([0.1, 0.2, 0.3, 0.4])
        model = build_bayesian_model(X, y, np.array([0.5, 0.5]), use_ar1_errors=False)
        names = set(model.named_vars.keys())
        assert "rho" not in names
        assert "y_obs" in names


class _FakeArray:
    def __init__(self, values):
        self.values = values


class _FakeTrace:
    def __init__(self, posterior, diverging=0):
        self.posterior = {k: _FakeArray(v) for k, v in posterior.items()}
        self.sample_stats = {"diverging": _FakeArray(np.array([diverging]))}


class TestPosteriorExtraction:
    def test_flattens_arrays(self):
        trace = _FakeTrace(
            {
                "intercept": np.array([[1.0, 2.0], [3.0, 4.0]]),
                "coeffs": np.array([[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]]),
                "sigma": np.array([[0.5, 0.6], [0.7, 0.8]]),
                "rho": np.array([[0.1, 0.2], [0.3, 0.4]]),
            }
        )
        draws = extract_posterior(trace, 2, use_ar1_errors=True)
        np.testing.assert_allclose(draws.post_int, [1, 2, 3, 4])
        assert draws.post_coeff.shape == (4, 2)
        np.testing.assert_allclose(draws.post_sigma, [0.5, 0.6, 0.7, 0.8])
        np.testing.assert_allclose(draws.post_rho, [0.1, 0.2, 0.3, 0.4])

    def test_no_ar1_rho_is_zeros(self):
        trace = _FakeTrace(
            {
                "intercept": np.array([1.0, 2.0]),
                "coeffs": np.array([[1.0, 2.0], [3.0, 4.0]]),
                "sigma": np.array([0.5, 0.6]),
            }
        )
        draws = extract_posterior(trace, 2, use_ar1_errors=False)
        np.testing.assert_allclose(draws.post_rho, [0.0, 0.0])


# ---------------------------------------------------------------------------
# Service end-to-end (injected fake builder/sampler, no PyMC sampling)
# ---------------------------------------------------------------------------
def _fake_builder(X, y, prior_sigmas, use_ar1_errors):
    return "fake-model"


def _make_fake_sampler(n_features, use_ar1=True):
    def fake_sampler(bmodel, **kwargs):
        posterior = {
            "intercept": np.array([0.0, 0.0, 1.0, 1.0]),
            "coeffs": np.array([[1.0, 1.0]] * 4),
            "sigma": np.array([1.0, 1.0, 1.0, 1.0]),
        }
        if use_ar1:
            posterior["rho"] = np.array([0.1, 0.2, 0.3, 0.4])
        return _FakeTrace(posterior, diverging=0)

    return fake_sampler


def _base_config(**overrides):
    kw = dict(
        method_name="test",
        control_list=("C1", "C2"),
        test_regions=("T",),
        geo_col="region",
        feature_cols=("f1",),
        time_series_frequency="weekly",
        frequency_config=WEEKLY,
        include_lagged_controls=False,
        lag_periods=1,
        use_structural_priors=False,
        use_ar1_errors=True,
        pre_start="2025-01-06",
        pre_end="2025-03-24",
        test_start="2025-03-31",
        test_end="2025-04-21",
        use_post=False,
    )
    kw.update(overrides)
    return BayesianConfig(**kw)


class TestService:
    def test_end_to_end_typed_result(self):
        agg, dates = _weekly_agg()
        structural = _structural_agg(
            ["T", "C1", "C2"],
            ["f1"],
            {"T": 10, "C1": 10, "C2": 10},
            {"T": [0.0], "C1": [1.0], "C2": [2.0]},
        )
        config = _base_config()
        res = run_bayesian(
            agg,
            structural,
            config,
            "Revenue",
            model_builder_fn=_fake_builder,
            sampler_fn=_make_fake_sampler(2),
        )
        assert isinstance(res, BayesianResult)
        assert res.completed is True
        assert res.warnings == () and res.errors == () and res.blockers == ()
        assert res.test_dates is not None and len(res.test_dates) == 4
        assert res.uplift_samples.shape == (4,)
        assert res.mean_uplift is not None
        assert res.rho_mean == pytest.approx(0.25)
        assert res.use_ar1_errors is True
        assert res.prior_style == "Standard weak prior"
        # structural_prior_df enriched with posterior coefficients
        df = res.structural_prior_df
        assert "Posterior Coefficient Mean" in df.columns
        assert "Posterior Coefficient 3%" in df.columns
        # trace kept separate
        assert hasattr(res.trace, "posterior")
        d = res.to_dict()
        assert "trace" not in d
        assert d["selected_metric"] == "Revenue"
        assert d["lag_drop_pct"] is None

    def test_insufficient_pre_period_returns_error_result(self):
        agg, dates = _weekly_agg(n_pre=3, n_test=4)
        config = _base_config(pre_end="2025-01-13", test_start="2025-01-20", test_end="2025-02-10")
        res = run_bayesian(agg, pd.DataFrame(), config, "Revenue")
        assert res.completed is False
        assert any("Not enough pre" in e for e in res.errors)

    def test_missing_test_period_returns_error_result(self):
        agg, dates = _weekly_agg()
        config = _base_config(test_start="2030-01-07", test_end="2030-02-01")
        res = run_bayesian(agg, pd.DataFrame(), config, "Revenue")
        assert res.completed is False
        assert any("No test period data" in e for e in res.errors)

    def test_ar1_non_contiguous_pre_blocks(self):
        # Drop one pre week so the pre-period has a calendar gap.
        dates = pd.date_range("2025-01-06", periods=16, freq="7D")
        test_vals = list(range(1, 17))
        agg = _validation_agg(
            dates,
            test_vals,
            {"C1": [v + 1 for v in test_vals], "C2": [v * 0.9 + 5 for v in test_vals]},
        )
        config = _base_config(
            pre_start="2025-01-06",
            pre_end="2025-03-17",  # pre = 2025-01-06..03-17 (11 weeks, includes a gap if one week missing)
            test_start="2025-03-24",
            test_end="2025-04-14",
        )
        # Remove 2025-02-10 from the aggregate (a pre-period week).
        agg = agg[agg["date"] != pd.Timestamp("2025-02-10")].reset_index(drop=True)
        res = run_bayesian(
            agg,
            pd.DataFrame(),
            config,
            "Revenue",
            model_builder_fn=_fake_builder,
            sampler_fn=_make_fake_sampler(2),
        )
        assert res.completed is False
        assert any("AR(1)" in b for b in res.blockers)

    def test_row_loss_warning_and_error(self):
        # 2 of 16 rows missing for C1 -> ~12.5% -> warning (no block)
        agg, dates = _weekly_agg(gap_index=2)
        agg2 = agg.copy()
        agg2.loc[(agg2["region"] == "C1") & (agg2["date"] == dates[2]), "kpi"] = np.nan
        config = _base_config()
        res = run_bayesian(
            agg2,
            pd.DataFrame(),
            config,
            "Revenue",
            model_builder_fn=_fake_builder,
            sampler_fn=_make_fake_sampler(2),
        )
        # 1 dropped of 16 rows is 6.25% -> no message at all (not >10)
        assert res.warnings == () and res.errors == ()

        # 6 of 16 rows missing -> 37.5% -> error but completed still possible
        agg3 = agg.copy()
        for i in range(0, 12, 2):
            agg3.loc[(agg3["region"] == "C1") & (agg3["date"] == dates[i]), "kpi"] = np.nan
        res3 = run_bayesian(
            agg3,
            pd.DataFrame(),
            config,
            "Revenue",
            model_builder_fn=_fake_builder,
            sampler_fn=_make_fake_sampler(2),
        )
        assert any("removed because the test series" in e for e in res3.errors)


# ---------------------------------------------------------------------------
# Reduced-sampling smoke workflow (slow; runs the REAL PyMC sampling path)
# ---------------------------------------------------------------------------
@pytest.mark.slow
class TestReducedSamplingSmoke:
    """End-to-end smoke with a tiny sampling profile (draws=20, tune=10, chains=1).

    Measured ~14s locally (mostly PyMC import) and stable/deterministic via
    random_seed=42. Deliberately slow-marked so the fast suite never runs it.
    """

    def test_tiny_sample_completes_with_real_trace(self):
        dates = pd.date_range("2025-01-06", periods=20, freq="7D")
        rows = []
        rng = np.random.default_rng(0)
        base = np.cumsum(rng.normal(0, 1, 20))
        for region, k in (("T", 1.0), ("C1", 1.1), ("C2", 0.9)):
            for d, b in zip(dates, base):
                rows.append(
                    {"date": d, "region": region, "kpi": max(50 + k * b + rng.normal(0, 2), 1)}
                )
        agg = pd.DataFrame(rows)
        structural = pd.DataFrame(
            {
                "region": ["T", "C1", "C2"],
                "Population": [10.0, 10.0, 10.0],
                "f1": [1.0, 2.0, 3.0],
            }
        )
        config = BayesianConfig(
            method_name="test",
            control_list=("C1", "C2"),
            test_regions=("T",),
            geo_col="region",
            feature_cols=("f1",),
            time_series_frequency="weekly",
            frequency_config=WEEKLY,
            include_lagged_controls=False,
            lag_periods=1,
            use_structural_priors=False,
            use_ar1_errors=True,
            pre_start="2025-01-06",
            pre_end="2025-03-24",
            test_start="2025-03-31",
            test_end="2025-04-21",
            use_post=False,
            mcmc_draws=20,
            mcmc_tune=10,
            mcmc_chains=1,
            mcmc_target_accept=0.95,
            mcmc_random_seed=42,
        )
        res = run_bayesian(agg, structural, config, "Revenue")
        assert res.completed is True
        assert res.blockers == () and res.errors == ()
        # uplift_samples is one value per posterior draw.
        assert res.uplift_samples.shape == (20,)
        assert res.mean_uplift is not None
        assert res.rho_mean is not None
        # Real PyMC InferenceData trace, kept separate from the summary.
        assert res.trace is not None
        assert "trace" not in res.to_dict()
