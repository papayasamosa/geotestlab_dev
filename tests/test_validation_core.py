"""Direct unit tests for the extracted validation core (Stage 2).

Covers, with small hand-calculable fixtures (not AppTest):
- weekly/daily frequency configuration;
- exact calendar lags and missing lag dates;
- model-matrix row-loss diagnostics;
- empty and missing controls;
- insufficient pre-period history;
- TimeSeriesSplit selection and fixed-alpha exploratory fallback;
- rolling-origin fold dates and discontinuous fold exclusion;
- placebo-window dates, cap behaviour, and available/used/skipped counts;
- uplift summary calculations and zero counterfactual denominator;
- Counterfactual Confidence driver precedence;
- serialisation of typed summaries;
- a deterministic end-to-end parity check (the authoritative parity with the
  current numerical goldens is the existing slow golden test suite).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import ElasticNet, ElasticNetCV
from sklearn.model_selection import TimeSeriesSplit

from geotestlab.validation import (
    add_lagged_control_features,
    build_model_matrix,
    build_regularized_model,
    calculate_overfit_gap,
    classify_autocorrelation_risk,
    classify_overfitting_risk,
    classify_rolling_bias_risk,
    classify_rolling_validation_error,
    classify_validation_method,
    combine_reliability_ratings,
    compute_metrics,
    durbin_watson_stat,
    get_frequency_config,
    get_reliability_drivers,
    infer_time_series_frequency,
    rolling_origin_validation,
    run_placebo_windows,
    run_validation,
    safe_tscv,
    smape,
    summarize_placebo_results,
    summarize_rolling_origin_folds,
)
from geotestlab.validation.models import (
    ValidationConfig,
    ValidationPeriods,
    ValidationResult,
)

WEEKLY = get_frequency_config("weekly")
DAILY = get_frequency_config("daily")


def _agg_frame(regions, dates, values_by_region) -> pd.DataFrame:
    """Build a long agg_df (date, region, kpi) for the given regions/dates."""
    rows = []
    for region in regions:
        for i, d in enumerate(dates):
            rows.append({"date": d, "region": region, "kpi": values_by_region[region][i]})
    return pd.DataFrame(rows)


def _validation_config(method="enet", **overrides) -> ValidationConfig:
    kwargs = dict(
        method_name=method,
        compute_uplift=False,
        placebo_length_periods=4,
        min_training_periods=13,
        include_lagged_controls=False,
        time_series_frequency="weekly",
        frequency_config=WEEKLY,
    )
    kwargs.update(overrides)
    return ValidationConfig(**kwargs)


def _periods(
    pre_start,
    pre_end,
    test_start=None,
    test_end=None,
    use_post=False,
    post_start=None,
    post_end=None,
) -> ValidationPeriods:
    return ValidationPeriods(
        pre_start=pd.Timestamp(pre_start),
        pre_end=pd.Timestamp(pre_end),
        test_start=pd.Timestamp(test_start) if test_start else None,
        test_end=pd.Timestamp(test_end) if test_end else None,
        use_post=use_post,
        post_start=pd.Timestamp(post_start) if post_start else None,
        post_end=pd.Timestamp(post_end) if post_end else None,
    )


# ---------------------------------------------------------------------------
# Frequency configuration
# ---------------------------------------------------------------------------


class TestFrequencyConfig:
    def test_weekly_defaults(self):
        assert WEEKLY.frequency == "weekly"
        assert WEEKLY.lag_periods == 1
        assert WEEKLY.lag_label == "1-week"
        assert WEEKLY.default_min_training_periods == 13
        assert WEEKLY.default_validation_horizon_periods == 4
        assert WEEKLY.period_label_singular == "week"
        assert WEEKLY.period_label_plural == "weeks"

    def test_daily_defaults(self):
        assert DAILY.frequency == "daily"
        assert DAILY.lag_periods == 7
        assert DAILY.lag_label == "7-day"
        assert DAILY.default_min_training_periods == 84
        assert DAILY.default_validation_horizon_periods == 28

    def test_unknown_frequency_falls_back_to_weekly(self):
        fc = get_frequency_config("monthly")
        assert fc.frequency == "weekly"
        assert fc.lag_periods == 1

    def test_dict_style_access(self):
        assert WEEKLY["lag_periods"] == 1
        assert WEEKLY.get("frequency") == "weekly"
        assert WEEKLY.get("missing", "default") == "default"
        with pytest.raises(KeyError):
            _ = WEEKLY["missing"]

    def test_infer_frequency(self):
        daily = pd.date_range("2025-01-01", periods=10, freq="D")
        weekly = pd.date_range("2025-01-06", periods=10, freq="W")
        assert infer_time_series_frequency(daily) == "daily"
        assert infer_time_series_frequency(weekly) == "weekly"
        assert infer_time_series_frequency(weekly[:1]) == "unknown"
        assert infer_time_series_frequency([pd.Timestamp("2025-01-06")]) == "unknown"


# ---------------------------------------------------------------------------
# Model matrix + calendar lags
# ---------------------------------------------------------------------------


class TestModelMatrix:
    def test_row_loss_diagnostics(self):
        dates = pd.date_range("2025-01-06", periods=5, freq="W")
        # C1 is missing on the 3rd date -> dropna removes that date for everyone.
        rows = []
        for region in ("Test", "C1", "C2"):
            for i, d in enumerate(dates):
                if region == "C1" and i == 2:
                    continue
                rows.append({"date": d, "region": region, "kpi": float(i + 1)})
        agg = pd.DataFrame(rows)
        model, diag = build_model_matrix(agg, ["C1", "C2"], ["Test"])
        assert diag.rows_before_dropna == 5
        assert diag.rows_after_dropna == 4
        assert diag.rows_dropped == 1
        assert round(diag.pct_rows_dropped, 2) == 20.0
        assert diag.control_columns_with_missing == ("C1",)
        assert len(model) == 4

    def test_clean_matrix_has_no_row_loss(self):
        dates = pd.date_range("2025-01-06", periods=5, freq="W")
        agg = _agg_frame(
            ["Test", "C1"],
            dates,
            {"Test": [1.0, 2, 3, 4, 5], "C1": [10.0, 20, 30, 40, 50]},
        )
        model, diag = build_model_matrix(agg, ["C1"], ["Test"])
        assert diag.rows_dropped == 0
        assert diag.pct_rows_dropped == 0.0
        assert diag.control_columns_with_missing == ()
        assert list(model.columns) == ["date", "test_kpi", "C1"]
        assert model["test_kpi"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_empty_controls(self):
        dates = pd.date_range("2025-01-06", periods=3, freq="W")
        agg = _agg_frame(["Test"], dates, {"Test": [1.0, 2.0, 3.0]})
        model, diag = build_model_matrix(agg, [], ["Test"])
        assert list(model.columns) == ["date", "test_kpi"]
        assert diag.control_columns_with_missing == ()

    def test_missing_control_absent_from_matrix(self):
        dates = pd.date_range("2025-01-06", periods=3, freq="W")
        agg = _agg_frame(["Test", "C1"], dates, {"Test": [1.0, 2.0, 3.0], "C1": [10.0, 20.0, 30.0]})
        model, _ = build_model_matrix(agg, ["C1", "GHOST"], ["Test"])
        # GHOST never appears -> no column, and it is not flagged as "with missing".
        assert "GHOST" not in model.columns
        assert "C1" in model.columns


class TestExactCalendarLags:
    def test_weekly_lag_is_exactly_seven_days(self):
        dates = pd.date_range("2025-01-06", periods=5, freq="W")
        agg = _agg_frame(
            ["Test", "C1"],
            dates,
            {"Test": [1.0, 2, 3, 4, 5], "C1": [10.0, 20, 30, 40, 50]},
        )
        model, _ = build_model_matrix(agg, ["C1"], ["Test"])
        lagged, feats, fmap, meta = add_lagged_control_features(
            model, ["C1"], lags=(1,), frequency_config=WEEKLY
        )
        # C1_lag1 at date D = C1 exactly 7 days earlier. The first row's lag
        # source date (7 days before 2025-01-06) is absent -> dropped.
        assert lagged["C1_lag1"].tolist() == [10.0, 20.0, 30.0, 40.0]
        assert lagged["test_kpi"].tolist() == [2.0, 3.0, 4.0, 5.0]
        assert feats == ["C1", "C1_lag1"]
        assert fmap["C1"] == {"current": "C1", "lag1": "C1_lag1"}
        assert meta["rows_dropped_due_to_lag"] == 1
        assert meta["rows_before_lag_drop"] == 5
        assert meta["rows_after_lag_drop"] == 4

    def test_daily_lag_is_seven_calendar_days(self):
        dates = pd.date_range("2025-01-01", periods=15, freq="D")
        agg = _agg_frame(
            ["Test", "C1"],
            dates,
            {"Test": list(range(15)), "C1": [10.0 + i for i in range(15)]},
        )
        model, _ = build_model_matrix(agg, ["C1"], ["Test"])
        lagged, feats, _, meta = add_lagged_control_features(
            model, ["C1"], lags=(7,), frequency_config=DAILY
        )
        # Lag 7: same day of week. First lagged row (2025-01-08) has lag = C1 at
        # 2025-01-01 = 10; the last row (2025-01-15) has lag = C1 at 2025-01-08 = 17.
        # First 7 rows have no source 7 days earlier -> dropped.
        assert lagged["C1_lag7"].iloc[0] == 10.0
        assert lagged["C1_lag7"].iloc[-1] == 17.0
        assert len(lagged) == 15 - 7
        assert meta["rows_dropped_due_to_lag"] == 7

    def test_missing_lag_dates_are_dropped_not_borrowed(self):
        dates = pd.date_range("2025-01-06", periods=5, freq="W")
        rows = []
        for region in ("Test", "C1"):
            for i, d in enumerate(dates):
                if region == "C1" and i == 2:
                    continue  # C1 missing on the 3rd date
                rows.append(
                    {"date": d, "region": region, "kpi": float(i + 1) if region == "Test" else 10.0}
                )
        agg = pd.DataFrame(rows)
        model, _ = build_model_matrix(agg, ["C1"], ["Test"])
        # model dates: the 3rd date is dropped entirely (inner join).
        assert len(model) == 4
        lagged, _, _, meta = add_lagged_control_features(
            model, ["C1"], lags=(1,), frequency_config=WEEKLY
        )
        # Row at the 3rd surviving date would need the (dropped) 2nd date as its lag
        # source -> that row is dropped, not borrowed. Only the 2nd and 4th surviving
        # dates keep a valid lag (their source date is present).
        assert lagged["date"].tolist() == [dates[1], dates[4]]
        assert lagged["C1_lag1"].tolist() == [10.0, 10.0]
        assert meta["rows_dropped_due_to_lag"] == 2


# ---------------------------------------------------------------------------
# Metrics + residual diagnostics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_smape_and_metrics_hand_calculable(self):
        actual = np.array([10.0, 20.0, 30.0])
        pred = np.array([10.0, 20.0, 30.0])
        assert smape(actual, pred) == 0.0
        corr, r2, s, rmse = compute_metrics(actual, pred)
        assert corr == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)
        assert rmse == pytest.approx(0.0)

    def test_durbin_watson_hand_calculable(self):
        # residuals with strong positive autocorrelation
        residuals = np.array([0.0, 1.0, 2.0, 3.0])
        dw = durbin_watson_stat(residuals)
        # diffs are all 1 -> sum(diff^2) = 3, denom = 14
        assert dw == pytest.approx(3.0 / 14.0)
        assert np.isnan(durbin_watson_stat([1.0, 2.0]))  # fewer than 3 -> nan
        assert np.isnan(durbin_watson_stat([0.0, 0.0, 0.0]))  # zero variance -> nan


# ---------------------------------------------------------------------------
# Regularisation: TimeSeriesSplit vs exploratory fallback
# ---------------------------------------------------------------------------


class TestRegularisation:
    def test_safe_tscv(self):
        assert safe_tscv(5, 5) is None
        tscv = safe_tscv(5, 20)
        assert isinstance(tscv, TimeSeriesSplit)
        assert tscv.get_n_splits() == 5

    def test_time_series_split_model_selection(self):
        model, status, used_cv = build_regularized_model("enet", 30, n_splits_pref=5)
        assert used_cv is True
        assert isinstance(model, ElasticNetCV)
        assert "TimeSeriesSplit" in status

    def test_fixed_alpha_exploratory_fallback(self):
        model, status, used_cv = build_regularized_model("enet", 5, n_splits_pref=5)
        assert used_cv is False
        assert isinstance(model, ElasticNet)
        assert "exploratory" in status.lower() or "Exploratory" in status
        assert "NOT cross-validated" in status

    def test_classify_validation_method(self):
        import pandas as pd

        all_cv = pd.DataFrame({"used_cv_fallback": [False, False]})
        partial = pd.DataFrame({"used_cv_fallback": [False, True]})
        none_cv = pd.DataFrame({"used_cv_fallback": [True, True]})
        assert classify_validation_method(all_cv, False) == "🟢 Rolling-origin validation"
        assert classify_validation_method(partial, False) == "🟡 Partial rolling-origin validation"
        assert classify_validation_method(none_cv, False) == "⚪ Insufficient validation history"
        assert classify_validation_method(all_cv, True) == "⚪ Insufficient validation history"
        assert classify_validation_method(None, False) == "⚪ Insufficient validation history"


# ---------------------------------------------------------------------------
# Rolling-origin validation
# ---------------------------------------------------------------------------


class TestRollingOrigin:
    def test_fold_dates_and_metrics(self):
        n = 20
        dates = pd.date_range("2025-01-06", periods=n, freq="W")
        rng = np.random.default_rng(1)
        X = rng.normal(size=(n, 1))
        y = 2.0 * X[:, 0] + rng.normal(0, 0.1, size=n)
        fold_df, smape_mean, rmse_mean, cv_status, skipped = rolling_origin_validation(
            X, y, WEEKLY, horizon=3, min_training_periods=6, dates=dates.tolist(), model_type="enet"
        )
        assert len(fold_df) >= 1
        assert skipped == 0
        # First fold: train Jan 6..start, test start..start+3; dates present.
        first = fold_df.iloc[0]
        assert first["test_start_date"] == dates[first["training_periods"]]
        assert first["test_end_date"] == dates[first["training_periods"] + 2]
        assert fold_df["forecast_horizon_periods"].iloc[0] == 3
        assert np.isfinite(smape_mean)
        assert "TimeSeriesSplit" in cv_status or "Insufficient history" in cv_status

    def test_discontinuous_fold_exclusion(self):
        n = 20
        dates = pd.date_range("2025-01-01", periods=n, freq="D")
        # Remove one date in the middle -> a calendar gap inside later windows.
        gap_date = dates[10]
        dates = dates[dates != gap_date]
        rng = np.random.default_rng(2)
        X = rng.normal(size=(len(dates), 1))
        y = rng.normal(size=(len(dates),))
        fold_df, _, _, _, skipped = rolling_origin_validation(
            X, y, DAILY, horizon=4, min_training_periods=6, dates=dates.tolist(), model_type="enet"
        )
        assert skipped >= 1

    def test_insufficient_history(self):
        X = np.zeros((5, 1))
        y = np.zeros(5)
        fold_df, smape_mean, rmse_mean, cv_status, _ = rolling_origin_validation(
            X, y, WEEKLY, horizon=4, min_training_periods=13, model_type="enet"
        )
        assert fold_df.empty
        assert np.isnan(smape_mean)
        assert np.isnan(rmse_mean)
        assert "No folds" in cv_status

    def test_summarize_rolling_origin_folds_excludes_fallback(self):
        fold_df = pd.DataFrame(
            {
                "used_cv_fallback": [False, False, True],
                "smape": [1.0, 3.0, 100.0],
                "bias_pct": [0.0, 2.0, 999.0],
                "uplift_error_pct": [1.0, -1.0, 999.0],
            }
        )
        summary = summarize_rolling_origin_folds(fold_df)
        assert summary["rolling_smape_p90"] == pytest.approx(np.percentile([1.0, 3.0], 90))
        assert summary["rolling_bias_pct_mean"] == pytest.approx(1.0)  # only CV folds
        assert summary["rolling_uplift_error_pct_median"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Placebo windows
# ---------------------------------------------------------------------------


class TestPlaceboWindows:
    def _pre_frame(self, n=20, freq="W"):
        dates = pd.date_range("2025-01-06", periods=n, freq=freq)
        model_pre = pd.DataFrame(
            {
                "date": dates,
                "test_kpi": np.arange(n, dtype=float),
                "C1": np.arange(n, dtype=float) * 2,
            }
        )
        return model_pre, dates

    def test_window_dates_and_counts(self):
        model_pre, dates = self._pre_frame(n=20)
        _, _, _, _, wd = run_placebo_windows(
            model_pre,
            ["C1"],
            dates.tolist(),
            min_training_periods=6,
            placebo_len=3,
            method_name="enet",
            frequency_config=WEEKLY,
        )
        # all_starts = range(6, 20-3+1) = range(6,18) -> 12 windows
        assert wd["windows_available"] == 12
        assert wd["windows_used"] == 12
        assert wd["windows_skipped_non_contiguous"] == 0

    def test_cap_behaviour(self):
        model_pre, dates = self._pre_frame(n=200, freq="D")
        _, _, _, _, wd = run_placebo_windows(
            model_pre,
            ["C1"],
            dates.tolist(),
            min_training_periods=14,
            placebo_len=7,
            method_name="enet",
            frequency_config=DAILY,
        )
        # many starts -> subsampled to at most 40 evenly-spaced windows
        assert wd["windows_available"] <= 40
        assert wd["windows_used"] <= 40

    def test_non_contiguous_windows_skipped(self):
        dates = pd.date_range("2025-01-06", periods=20, freq="W")
        gap_date = dates[10]
        dates = dates[dates != gap_date]
        model_pre = pd.DataFrame(
            {
                "date": dates,
                "test_kpi": np.arange(len(dates), dtype=float),
                "C1": np.arange(len(dates), dtype=float),
            }
        )
        _, _, _, _, wd = run_placebo_windows(
            model_pre,
            ["C1"],
            dates.tolist(),
            min_training_periods=6,
            placebo_len=3,
            method_name="enet",
            frequency_config=WEEKLY,
        )
        assert wd["windows_skipped_non_contiguous"] >= 1
        assert wd["windows_used"] + wd["windows_skipped_non_contiguous"] == wd["windows_available"]

    def test_insufficient_history_no_windows(self):
        model_pre, dates = self._pre_frame(n=8)
        placebos, pcts, smapes, rmses, wd = run_placebo_windows(
            model_pre,
            ["C1"],
            dates.tolist(),
            min_training_periods=6,
            placebo_len=4,
            method_name="enet",
            frequency_config=WEEKLY,
        )
        assert placebos == [] and pcts == [] and smapes == [] and rmses == []
        assert wd["windows_available"] == 0

    def test_invalid_placebo_len(self):
        model_pre, dates = self._pre_frame(n=20)
        _, _, _, _, wd = run_placebo_windows(
            model_pre,
            ["C1"],
            dates.tolist(),
            min_training_periods=6,
            placebo_len=None,
            method_name="enet",
            frequency_config=WEEKLY,
        )
        assert wd["windows_available"] == 0


class TestPlaceboSummary:
    def test_hand_calculable_summary(self):
        placebos = [0.0, 10.0, 20.0, 30.0]
        pcts = [0.0, 10.0, 20.0, 30.0]
        smapes = [1.0, 2.0, 3.0, 4.0]
        rmses = [5.0, 6.0, 7.0, 8.0]
        s = summarize_placebo_results(placebos, pcts, smapes, rmses, uplift=25.0)
        assert s["median_uplift"] == pytest.approx(15.0)
        assert s["median_placebo_uplift_pct"] == pytest.approx(15.0)
        assert s["median_placebo_smape"] == pytest.approx(2.5)
        assert s["median_placebo_rmse"] == pytest.approx(6.5)
        # placebos < 25: [0, 10, 20] -> 75th percentile rank
        assert s["percentile_rank"] == pytest.approx(75.0)
        # placebos >= 25: only 30 -> one-sided p = 0.25
        assert s["p_one_sided"] == pytest.approx(0.25)
        # |p - 15| >= |25 - 15| = 10: 0 and 30 -> two-sided p = 0.5
        assert s["p_two_sided"] == pytest.approx(0.5)
        assert s["z_score"] == pytest.approx((25.0 - 15.0) / (np.std(placebos) + 1e-12))

    def test_no_placebos_all_nan(self):
        s = summarize_placebo_results([], [], [], [], uplift=5.0)
        for key, value in s.items():
            assert np.isnan(value), key

    def test_zero_counterfactual_denominator(self):
        # A placebo window whose predicted sum was zero produced NaN uplift-%.
        s = summarize_placebo_results(
            [10.0, 20.0], [np.nan, 10.0], [1.0, 2.0], [3.0, 4.0], uplift=15.0
        )
        assert np.isnan(s["median_placebo_uplift_pct"])
        # Uplift-based statistics still use the raw placebos.
        assert s["median_uplift"] == pytest.approx(15.0)
        assert s["p_one_sided"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Counterfactual Confidence
# ---------------------------------------------------------------------------


class TestCounterfactualConfidence:
    def test_priority_cascade(self):
        green = {
            "rolling validation error": "🟢 Low",
            "overfitting gap": "🟢 Low",
            "autocorrelation risk": "🟢 Low",
            "rolling bias": "🟢 Low",
        }
        assert combine_reliability_ratings(green) == "🟢 High confidence"

        # Primary check red overrides everything.
        red_primary = dict(green, **{"rolling validation error": "🔴 High"})
        assert combine_reliability_ratings(red_primary) == "🔴 Low confidence"

        # Primary check unavailable -> insufficient regardless of others.
        unavailable = dict(green, **{"rolling validation error": "⚪ Insufficient data"})
        assert combine_reliability_ratings(unavailable) == "⚪ Insufficient data"

        # Moderate primary caps at moderate.
        moderate_primary = dict(green, **{"rolling validation error": "🟡 Moderate"})
        assert combine_reliability_ratings(moderate_primary) == "🟡 Moderate confidence"

        # Green primary but a flagged secondary caps at moderate (never low).
        secondary_flagged = dict(green, **{"rolling bias": "🔴 High"})
        assert combine_reliability_ratings(secondary_flagged) == "🟡 Moderate confidence"
        secondary_yellow = dict(green, **{"overfitting gap": "🟡 Moderate"})
        assert combine_reliability_ratings(secondary_yellow) == "🟡 Moderate confidence"

    def test_drivers(self):
        green = {
            "rolling validation error": "🟢 Low",
            "overfitting gap": "🟢 Low",
            "autocorrelation risk": "🟢 Low",
            "rolling bias": "🟢 Low",
        }
        assert get_reliability_drivers(green) == "Validation checks passed"
        assert (
            get_reliability_drivers(
                dict(green, **{"rolling validation error": "⚪ Insufficient data"})
            )
            == "Insufficient validation data to assess confidence"
        )
        drivers = get_reliability_drivers(
            dict(green, **{"rolling validation error": "🔴 High", "rolling bias": "🟡 Moderate"})
        )
        assert "High rolling validation error" in drivers
        assert "moderate rolling bias" in drivers

    def test_classifiers_and_overfit_gap(self):
        assert classify_autocorrelation_risk(2.0) == "🟢 Low"
        assert classify_autocorrelation_risk(1.3) == "🟡 Moderate"
        assert classify_autocorrelation_risk(1.0) == "🔴 High"
        assert classify_autocorrelation_risk(np.nan) == "⚪ Insufficient data"
        assert calculate_overfit_gap(2.0, 5.0) == pytest.approx(3.0)
        assert np.isnan(calculate_overfit_gap(np.nan, 5.0))
        assert classify_overfitting_risk(2.0) == "🟢 Low"
        assert classify_rolling_validation_error(12.0) == "🟡 Moderate"
        assert classify_rolling_bias_risk(6.0) == "🟡 Moderate"


# ---------------------------------------------------------------------------
# Service + typed result serialisation
# ---------------------------------------------------------------------------


class TestValidationService:
    def _clean_agg(self, n=30):
        dates = pd.date_range("2025-01-06", periods=n, freq="W")
        rng = np.random.default_rng(7)
        shared = 100.0 + rng.normal(0, 3, size=n).cumsum() * 0.1
        values = {
            "Test": shared + rng.normal(0, 1, size=n),
            "C1": shared + rng.normal(0, 1, size=n),
            "C2": shared + rng.normal(0, 1, size=n),
        }
        return _agg_frame(["Test", "C1", "C2"], dates, values), dates

    def test_insufficient_pre_period_history(self):
        dates = pd.date_range("2025-01-06", periods=5, freq="W")
        agg = _agg_frame(
            ["Test", "C1"], dates, {"Test": [1.0, 2, 3, 4, 5], "C1": [10.0, 20, 30, 40, 50]}
        )
        res = run_validation(
            agg,
            ["C1"],
            ["Test"],
            _validation_config(),
            _periods(dates[0], dates[-1]),
        )
        assert res.ok is False
        assert res.insufficient_pre_period is True

    def test_missing_control_is_a_blocker(self):
        dates = pd.date_range("2025-01-06", periods=30, freq="W")
        agg = _agg_frame(
            ["Test", "C1"],
            dates,
            {"Test": [1.0 + i for i in range(30)], "C1": [10.0 + i for i in range(30)]},
        )
        res = run_validation(
            agg,
            ["C1", "GHOST"],
            ["Test"],
            _validation_config(),
            _periods(dates[0], dates[-1]),
        )
        assert res.ok is False
        assert res.blockers
        assert "GHOST" in res.blockers[0]

    def test_row_loss_becomes_structured_warning(self):
        dates = pd.date_range("2025-01-06", periods=30, freq="W")
        rows = []
        for region in ("Test", "C1"):
            for i, d in enumerate(dates):
                kpi = float(i + 1)
                if region == "C1" and i % 6 == 0:
                    kpi = np.nan  # NaN KPI values (not absent dates) trigger row loss
                rows.append({"date": d, "region": region, "kpi": kpi})
        agg = pd.DataFrame(rows)
        res = run_validation(
            agg,
            ["C1"],
            ["Test"],
            _validation_config(),
            _periods(dates[0], dates[-1]),
        )
        assert res.ok is True
        assert res.warnings  # row-loss warning present
        assert res.errors == ()
        assert res.blockers == ()

    def test_end_to_end_typed_result_and_serialisation(self):
        agg, dates = self._clean_agg(n=40)
        res = run_validation(
            agg,
            ["C1", "C2"],
            ["Test"],
            _validation_config(compute_uplift=True, placebo_length_periods=4),
            _periods(
                dates[0],
                dates[-5],
                test_start=dates[-4],
                test_end=dates[-1],
            ),
        )
        assert isinstance(res, ValidationResult)
        assert res.ok is True
        assert res.insufficient_pre_period is False

        # Typed diagnostics populated.
        assert res.matrix_diagnostics.rows_dropped == 0
        assert res.rolling.fold_df is not None and len(res.rolling.fold_df) >= 1
        assert res.placebo.windows_available >= 1
        assert res.confidence.rating in (
            "🟢 High confidence",
            "🟡 Moderate confidence",
            "🔴 Low confidence",
            "⚪ Insufficient data",
        )

        # Serialisable summary: legacy keys present; fitted objects kept separate.
        d = res.to_dict()
        assert d is res.summary
        assert "rolling_smape_mean" in d
        assert "placebo_window_diagnostics" in d
        assert "counterfactual_reliability" in d
        assert "model" not in d
        assert "scaler" not in d
        assert res.model is not None
        assert res.scaler is not None
        # frequency_config round-trips through the summary as dict-compatible.
        assert d["frequency_config"]["lag_periods"] == 1
        assert d["time_series_frequency"] == "weekly"
        assert d["n_pre_periods"] == len(d["y_pre"])

    def test_typed_summary_parity_smoke(self):
        """Small deterministic parity: clean weekly validation reproduces expected
        structural properties; the authoritative golden parity is the slow suite."""
        agg, dates = self._clean_agg(n=52)
        res = run_validation(
            agg,
            ["C1", "C2"],
            ["Test"],
            _validation_config(compute_uplift=False),
            _periods(dates[0], dates[-1]),
        )
        assert res.ok
        assert len(res.rolling.fold_df) <= 20  # fold subsampling cap
        assert np.isfinite(res.rolling.rolling_smape_mean)
        assert res.regularisation.validation_method_label in (
            "🟢 Rolling-origin validation",
            "🟡 Partial rolling-origin validation",
            "⚪ Insufficient validation history",
        )
        assert res.confidence.rating is not None
