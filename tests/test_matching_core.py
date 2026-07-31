"""Pure tests for the ``geotestlab.matching`` core (Stage 4 extraction).

These tests exercise the extracted matching package directly (no Streamlit,
no AppTest): hand-calculable metric/strategy behaviour, parity between the
vectorised scorer and the reference implementation, seed reproducibility,
empty/impossible pools, non-finite handling, KPI-pattern preparation, and the
typed serialisable models.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest

from geotestlab.matching import (
    POPULATION_COL,
    FeatureWeightConfig,
    MatchConfig,
    MatchDiagnostics,
    MatchResult,
    aggregate_market_data,
    basic_strategy,
    build_kpi_pattern_agg_df,
    build_kpi_pattern_wide,
    calculate_experiment_population_coverage,
    calculate_metrics,
    calculate_metrics_from_flat,
    coerce_kpi_date_values,
    filter_kpi_rows,
    fit_structural_stats,
    get_numeric_metric_columns,
    get_population_column,
    impute_missing_features,
    index_kpi_series_to_100,
    intermediate_strategy,
    make_fast_metrics_fn,
    nearest_neighbor_start,
    normalise_column_names,
    prepare_market_dataframe,
    preprocess_data,
    read_kpi_pattern_excel,
    retain_kpi_dates,
    stochastic_genetic_search,
    to_match_result,
    weighted_average_vectorized,
    weighted_profile,
)

FEATURES = ["f1", "f2"]


def _eligible_frames():
    """Hand-calculable fixture: 2 test regions + 1 control region."""
    test_df = pd.DataFrame(
        {
            "geo": ["T1", "T2"],
            "f1": [10.0, 30.0],
            "f2": [20.0, 40.0],
            POPULATION_COL: [1.0, 1.0],
        }
    )
    control_df = pd.DataFrame({"geo": ["C1"], "f1": [10.0], "f2": [50.0], POPULATION_COL: [1.0]})
    eligible_df = pd.concat([test_df, control_df], ignore_index=True)
    means, stds = fit_structural_stats(eligible_df, FEATURES)
    return test_df, control_df, eligible_df, means, stds


def _pool_frames():
    """Small pool where nearest-neighbour picks are obvious in raw space."""
    pool_df = pd.DataFrame(
        {
            "geo": ["P0", "P1", "P2", "P3", "P4"],
            "f1": [0.0, 1.0, 2.0, 10.0, 11.0],
            "f2": [0.0, 0.0, 0.0, 10.0, 10.0],
            POPULATION_COL: [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    ).set_index("geo")
    test_df_run = pd.DataFrame(
        {"geo": ["T"], "f1": [0.1], "f2": [0.05], POPULATION_COL: [1.0]}
    ).set_index("geo")
    eligible_df = pd.concat([pool_df, test_df_run])
    means, stds = fit_structural_stats(eligible_df, FEATURES)
    return pool_df, test_df_run, means, stds


# ---------------------------------------------------------------------------
# Typed models
# ---------------------------------------------------------------------------


class TestTypedModels:
    def test_match_config_defaults(self):
        cfg = MatchConfig()
        assert cfg.max_hill_climbing_swaps == 15
        assert cfg.seed == 42
        assert cfg.smd_good_threshold == 0.20
        assert isinstance(cfg, tuple) is False
        # Frozen: immutability
        with pytest.raises(AttributeError):
            cfg.seed = 1  # type: ignore[misc]

    def test_feature_weight_config_roundtrip(self):
        fw = FeatureWeightConfig.from_dict({"f1": 2.0, "f2": 0.5})
        assert fw.to_dict() == {"f1": 2.0, "f2": 0.5}
        assert fw.weights == (("f1", 2.0), ("f2", 0.5))
        # JSON round-trip safe (tuple of pairs)
        import json

        restored = FeatureWeightConfig(tuple(json.loads(json.dumps(fw.weights))))
        assert restored.to_dict() == {"f1": 2.0, "f2": 0.5}

    def test_match_result_is_serialisable(self):
        result = to_match_result(
            "Greedy (Nearest Neighbor)",
            ["P0", "P1"],
            {"weighted_structural_distance": 1.5, "mean_abs_smd": 0.2, "smd_list": [0.1, 0.3]},
            [1.5],
            0,
            seed=42,
        )
        assert isinstance(result, MatchResult)
        assert result.strategy == "Greedy (Nearest Neighbor)"
        assert result.control_indices == ("P0", "P1")
        assert result.weighted_structural_distance == 1.5
        assert result.smd_list == (0.1, 0.3)
        assert result.seed == 42
        with pytest.raises(AttributeError):
            result.control_indices = ("X",)  # type: ignore[misc]

    def test_match_diagnostics(self):
        d = MatchDiagnostics(
            strategy="Stochastic (Genetic Search)",
            weighted_structural_distance=1.2,
            mean_abs_smd=0.3,
            control_group_size=4,
            test_group_size=1,
            seed=7,
            candidates_evaluated=123,
            convergence=(1.5, 1.3, 1.2),
        )
        assert d.candidates_evaluated == 123
        assert d.convergence == (1.5, 1.3, 1.2)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestWeightedProfile:
    def test_population_weighted_means_hand_calculable(self):
        df = pd.DataFrame({"f1": [10.0, 30.0], "f2": [20.0, 40.0], POPULATION_COL: [1.0, 3.0]})
        profile = weighted_profile(df, FEATURES)
        # f1: (10*1 + 30*3)/4 = 25 ; f2: (20*1 + 40*3)/4 = 35
        assert profile["f1"] == pytest.approx(25.0)
        assert profile["f2"] == pytest.approx(35.0)

    def test_equal_weighted_fallback_without_population(self):
        df = pd.DataFrame({"f1": [10.0, 30.0], "f2": [20.0, 40.0]})
        profile = weighted_profile(df, FEATURES)
        assert profile["f1"] == pytest.approx(20.0)
        assert profile["f2"] == pytest.approx(30.0)

    def test_equal_weighted_fallback_when_population_sums_to_zero(self):
        df = pd.DataFrame({"f1": [10.0, 30.0], POPULATION_COL: [0.0, 0.0]})
        profile = weighted_profile(df, ["f1"])
        assert profile["f1"] == pytest.approx(20.0)


class TestCalculateMetricsHandCalculable:
    def test_metrics_match_hand_computation(self):
        test_df, control_df, _eligible, means, stds = _eligible_frames()
        metrics = calculate_metrics(
            test_df, control_df, FEATURES, {"f1": 1.0, "f2": 1.0}, means, stds
        )
        # z_test - z_control squared contributions (computed analytically):
        # f1 -> 1.125 ; f2 -> 2.571428... ; distance = sqrt(3.6964286)
        assert metrics["weighted_structural_distance"] == pytest.approx(
            np.sqrt(3.6964286), rel=1e-6
        )
        # smd_list: |10|/9.42809 = 1.06066 ; |-20|/12.4722 = 1.60357
        assert metrics["smd_list"][0] == pytest.approx(1.06066, rel=1e-4)
        assert metrics["smd_list"][1] == pytest.approx(1.60357, rel=1e-4)
        assert metrics["mean_abs_smd"] == pytest.approx((1.06066 + 1.60357) / 2, rel=1e-4)

    def test_empty_features_returns_zero_metrics(self):
        test_df, control_df, _eligible, means, stds = _eligible_frames()
        metrics = calculate_metrics(test_df, control_df, [], {}, means, stds)
        assert metrics["weighted_structural_distance"] == 0.0
        assert metrics["smd_list"] == []

    def test_zero_variance_feature_produces_nan_smd(self):
        test_df = pd.DataFrame({"geo": ["T"], "f1": [5.0], "f2": [5.0], POPULATION_COL: [1.0]})
        control_df = pd.DataFrame({"geo": ["C"], "f1": [5.0], "f2": [5.0], POPULATION_COL: [1.0]})
        eligible_df = pd.concat([test_df, control_df], ignore_index=True)
        means, stds = fit_structural_stats(eligible_df, FEATURES)  # f1 std == 0
        metrics = calculate_metrics(test_df, control_df, FEATURES, {}, means, stds)
        assert np.isnan(metrics["smd_list"][0])
        assert metrics["weighted_structural_distance"] == pytest.approx(0.0)

    def test_calculate_metrics_from_flat_matches(self):
        test_df, control_df, _eligible, means, stds = _eligible_frames()
        direct = calculate_metrics(
            test_df, control_df, FEATURES, {"f1": 2.0, "f2": 1.0}, means, stds
        )
        flat = calculate_metrics_from_flat(
            test_df,
            control_df,
            tuple(FEATURES),
            (2.0, 1.0),
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        assert flat["weighted_structural_distance"] == pytest.approx(
            direct["weighted_structural_distance"]
        )


class TestFastMetricsParity:
    @pytest.mark.parametrize("n_controls", [1, 2, 3])
    def test_fast_metrics_matches_calculate_metrics(self, n_controls):
        pool_df, test_df_run, means, stds = _pool_frames()
        weights = {"f1": 1.5, "f2": 0.5}
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, weights, means, stds)
        idx = list(pool_df.index[:n_controls])
        fast_m = fast(idx)
        ref_m = calculate_metrics(test_df_run, pool_df.loc[idx], FEATURES, weights, means, stds)
        assert fast_m["weighted_structural_distance"] == pytest.approx(
            ref_m["weighted_structural_distance"], rel=1e-12
        )
        assert fast_m["mean_abs_smd"] == pytest.approx(ref_m["mean_abs_smd"], rel=1e-12)
        assert fast_m["smd_list"] == pytest.approx(ref_m["smd_list"], rel=1e-12)

    def test_fast_metrics_empty_group_defers_to_reference(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        m = fast([])
        ref = calculate_metrics(test_df_run, pool_df.loc[[]], FEATURES, {}, means, stds)
        # Empty control group defers to the reference implementation: its
        # profile is NaN (no rows), so the distance is NaN — not 0.
        assert np.isnan(m["weighted_structural_distance"])
        assert np.isnan(ref["weighted_structural_distance"])

    def test_fast_metrics_no_features_returns_zeros(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, [], {}, means, stds)
        m = fast(["P0"])
        assert m["weighted_structural_distance"] == pytest.approx(0.0)
        assert m["smd_list"] == []


class TestPreprocess:
    def test_preprocess_shapes(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        weights = {"f1": 1.0, "f2": 1.0}
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            weights,
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        assert p_scaled.shape == (len(pool_df), 2)
        assert t_cent.shape == (1, 2)
        assert np.allclose(w_vec, [1.0, 1.0])


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


class TestBasicStrategy:
    def test_selects_nearest_neighbors(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        idx_1, _ = basic_strategy(pool_df, p_scaled, t_cent, 1, fast)
        assert idx_1 == ["P0"]
        idx_2, _ = basic_strategy(pool_df, p_scaled, t_cent, 2, fast)
        assert idx_2 == ["P0", "P1"]

    def test_n_larger_than_pool_clamps(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        idx, metrics = basic_strategy(pool_df, p_scaled, t_cent, 100, fast)
        assert len(idx) == len(pool_df)
        assert set(idx) == set(pool_df.index)


class TestIntermediateStrategy:
    def test_never_worse_than_basic_and_valid_indices(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        for n in (1, 2, 3):
            idx, metrics, conv = intermediate_strategy(
                pool_df, p_scaled, t_cent, n, fast, max_hill_climbing_swaps=3
            )
            assert len(idx) == n
            assert len(set(idx)) == n
            assert all(i in pool_df.index for i in idx)
            assert conv == sorted(conv, reverse=True)  # non-increasing best scores
            basic_idx, _ = basic_strategy(pool_df, p_scaled, t_cent, n, fast)
            basic_score = fast(basic_idx)["weighted_structural_distance"]
            assert metrics["weighted_structural_distance"] <= basic_score + 1e-12

    def test_improves_score_when_swap_available(self):
        # A pool where the initial NN group is sub-optimal: place a lone near
        # neighbour far from the rest so swapping it out improves the score.
        pool_df = pd.DataFrame(
            {
                "geo": ["P0", "P1", "P2", "P3"],
                "f1": [0.0, 1.0, 2.0, 3.0],
                "f2": [0.0, 0.0, 0.0, 0.0],
                POPULATION_COL: [1.0, 1.0, 1.0, 1.0],
            }
        ).set_index("geo")
        test_df_run = pd.DataFrame(
            {"geo": ["T"], "f1": [1.5], "f2": [0.0], POPULATION_COL: [1.0]}
        ).set_index("geo")
        eligible_df = pd.concat([pool_df, test_df_run])
        means, stds = fit_structural_stats(eligible_df, FEATURES)
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        idx, metrics, conv = intermediate_strategy(
            pool_df, p_scaled, t_cent, 2, fast, max_hill_climbing_swaps=3
        )
        basic_idx, _ = basic_strategy(pool_df, p_scaled, t_cent, 2, fast)
        assert (
            metrics["weighted_structural_distance"]
            <= fast(basic_idx)["weighted_structural_distance"] + 1e-12
        )
        assert len(conv) >= 1


class TestStochasticGeneticSearch:
    def test_seed_reproducibility(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        nn_start = nearest_neighbor_start(pool_df, p_scaled, t_cent, 2)
        kwargs = dict(
            pool_df=pool_df,
            test_df_run=test_df_run,
            active_features=FEATURES,
            weights={"f1": 1.0, "f2": 1.0},
            n=2,
            calculate_metrics_fn=calculate_metrics,
            eligible_means=means,
            eligible_stds=stds,
            nn_start_idx=nn_start,
            n_iterations=50,
            random_state=42,
            fast_metrics_fn=fast,
        )
        a = stochastic_genetic_search(**kwargs)
        b = stochastic_genetic_search(**kwargs)
        assert a[0] == b[0]
        assert a[1]["weighted_structural_distance"] == b[1]["weighted_structural_distance"]
        assert a[2] == b[2]
        assert a[3] == b[3]

    def test_result_is_valid_and_improves_or_matches_start(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        fast = make_fast_metrics_fn(pool_df, test_df_run, FEATURES, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            tuple(means[f] for f in FEATURES),
            tuple(stds[f] for f in FEATURES),
        )
        nn_start = nearest_neighbor_start(pool_df, p_scaled, t_cent, 2)
        best_idx, best_metrics, evaluated, conv = stochastic_genetic_search(
            pool_df,
            test_df_run,
            FEATURES,
            {"f1": 1.0, "f2": 1.0},
            2,
            calculate_metrics,
            means,
            stds,
            nn_start_idx=nn_start,
            n_iterations=50,
            random_state=1,
            fast_metrics_fn=fast,
        )
        assert len(best_idx) == 2
        assert len(set(best_idx)) == 2
        start_score = fast(nn_start)["weighted_structural_distance"]
        assert best_metrics["weighted_structural_distance"] <= start_score + 1e-12
        assert evaluated > 0
        assert conv == sorted(conv, reverse=True)

    def test_impossible_pool_size_returns_empty(self):
        pool_df, test_df_run, means, stds = _pool_frames()
        best_idx, _metrics, evaluated, conv = stochastic_genetic_search(
            pool_df,
            test_df_run,
            FEATURES,
            {},
            99,  # n > pool size
            calculate_metrics,
            means,
            stds,
            nn_start_idx=[],
            n_iterations=10,
        )
        assert best_idx == []
        assert evaluated == 0
        assert conv == []

    def test_benchmark_on_larger_pool(self):
        rng = np.random.default_rng(0)
        n_pool = 200
        pool_df = pd.DataFrame(
            {
                "geo": [f"R{i}" for i in range(n_pool)],
                "f1": rng.normal(50, 10, n_pool),
                "f2": rng.normal(20, 5, n_pool),
                "f3": rng.normal(100, 20, n_pool),
                POPULATION_COL: rng.uniform(10, 100, n_pool),
            }
        ).set_index("geo")
        test_df_run = pool_df.sample(1, random_state=3)
        features = ["f1", "f2", "f3"]
        means, stds = fit_structural_stats(pool_df, features)
        fast = make_fast_metrics_fn(pool_df, test_df_run, features, {}, means, stds)
        w_vec, p_scaled, t_cent = preprocess_data(
            pool_df,
            test_df_run,
            features,
            {"f1": 1.0, "f2": 1.0, "f3": 1.0},
            tuple(means[f] for f in features),
            tuple(stds[f] for f in features),
        )
        import time

        start = time.perf_counter()
        idx, metrics, conv = intermediate_strategy(
            pool_df, p_scaled, t_cent, 8, fast, max_hill_climbing_swaps=15
        )
        elapsed = time.perf_counter() - start
        assert len(idx) == 8
        assert elapsed < 20.0  # generous bound; guards against pathological regressions


# ---------------------------------------------------------------------------
# Structural preparation
# ---------------------------------------------------------------------------


class TestStructuralPrep:
    def test_weighted_average_vectorized_hand_calculable(self):
        df = pd.DataFrame(
            {"geo": ["A", "B"], "m1": [10.0, 30.0], "m2": [20.0, 40.0], POPULATION_COL: [1.0, 3.0]}
        )
        row = weighted_average_vectorized(df, ["m1", "m2"], POPULATION_COL)
        assert row["m1"] == pytest.approx(25.0)  # (10*1 + 30*3)/4
        assert row["m2"] == pytest.approx(35.0)  # (20*1 + 40*3)/4
        assert row[POPULATION_COL] == pytest.approx(4.0)

    def test_weighted_average_vectorized_empty_value_cols(self):
        df = pd.DataFrame({"geo": ["A"], POPULATION_COL: [5.0]})
        row = weighted_average_vectorized(df, [], POPULATION_COL)
        assert row[POPULATION_COL] == pytest.approx(5.0)

    def test_prepare_market_dataframe(self):
        df = pd.DataFrame(
            {
                "Region": ["A", "B", "C"],
                "Total Population": ["100", "0", "200"],
                "m1": ["1", "2", "3"],
            }
        )
        out = prepare_market_dataframe(df)
        assert POPULATION_COL in out.columns
        assert out[POPULATION_COL].tolist() == [100.0, 200.0]  # zero-pop row dropped

    def test_aggregate_market_data(self):
        market_df = pd.DataFrame(
            {
                "Market": ["US", "US", "US"],
                "Region": ["A", "A", "B"],
                POPULATION_COL: [1.0, 3.0, 5.0],
                "m1": [10.0, 30.0, 50.0],
            }
        )
        agg = aggregate_market_data(market_df, "Region", ["m1"])
        assert list(agg["Region"]) == ["A", "B"]
        row_a = agg[agg["Region"] == "A"].iloc[0]
        assert row_a["m1"] == pytest.approx(25.0)  # (10*1 + 30*3)/4

    def test_get_numeric_metric_columns(self):
        df = pd.DataFrame(
            {
                "Region": ["A", "B"],
                "Area": [1, 2],
                "m1": [10.0, 20.0],
                "m2": ["1.5", "2.5"],
                "note": ["x", "y"],
            }
        )
        cols = get_numeric_metric_columns(df, ["Region"])
        assert "m1" in cols
        assert "m2" in cols
        assert "Area" not in cols
        assert "note" not in cols
        assert POPULATION_COL not in cols

    def test_get_population_column(self):
        df = pd.DataFrame({"Total Population": [1.0]})
        assert get_population_column(df) == "Total Population"
        df2 = pd.DataFrame({"Population": [1.0]})
        assert get_population_column(df2) == "Population"

    def test_normalise_column_names(self):
        df = pd.DataFrame({"  f1  ": [1], "Unnamed: 0": [2], "f2": [3]})
        out = normalise_column_names(df)
        assert list(out.columns) == ["f1", "f2"]

    def test_impute_missing_features(self):
        df = pd.DataFrame({"f1": [1.0, np.nan, 3.0], "f2": [np.nan, np.nan, np.nan]})
        out = impute_missing_features(df, ["f1", "f2"])
        assert out["f1"].tolist() == [1.0, 2.0, 3.0]  # median 2
        assert out["f2"].tolist() == [0.0, 0.0, 0.0]  # all-NaN -> 0

    def test_coverage(self):
        agg_df = pd.DataFrame({"geo": ["A", "B", "C"], POPULATION_COL: [100.0, 200.0, 300.0]})
        assert calculate_experiment_population_coverage(
            ["A"], agg_df, "geo", 600.0
        ) == pytest.approx(100.0 / 6)
        assert calculate_experiment_population_coverage([], agg_df, "geo", 600.0) == 0.0
        assert calculate_experiment_population_coverage(["A"], agg_df, "geo", 0) == 0.0


# ---------------------------------------------------------------------------
# KPI-pattern preparation
# ---------------------------------------------------------------------------


class TestKpiPatternPrep:
    def test_index_to_100_hand_calculable(self):
        wide = pd.DataFrame(
            {"20240101": [100.0, 10.0], "20240108": [200.0, 20.0], "20240115": [300.0, 30.0]},
            index=pd.Index(["A", "B"], name="region"),
        )
        indexed = index_kpi_series_to_100(wide)
        # A mean 200 -> [50, 100, 150]; B mean 20 -> [50, 100, 150]
        expected = pd.DataFrame(
            {"20240101": [50.0, 50.0], "20240108": [100.0, 100.0], "20240115": [150.0, 150.0]},
            index=pd.Index(["A", "B"], name="region"),
        )
        pd.testing.assert_frame_equal(indexed, expected)

    def test_index_to_100_drops_nan_rows(self):
        wide = pd.DataFrame(
            {"d1": [100.0, 10.0, 5.0], "d2": [200.0, np.nan, 10.0]},
            index=pd.Index(["A", "B", "C"], name="region"),
        )
        indexed = index_kpi_series_to_100(wide)
        assert list(indexed.index) == ["A", "C"]  # B has NaN -> dropped

    def test_filter_kpi_rows_drops_blank_agg(self):
        df = pd.DataFrame(
            {
                "metric": ["visits", "visits", "visits", "visits"],
                "region": ["A", "B", "", np.nan],
                "d1": [1.0, 2.0, 3.0, 4.0],
            }
        )
        filtered, dropped = filter_kpi_rows(df, "metric", "visits", "region")
        assert dropped == 2
        assert list(filtered["region"]) == ["A", "B"]

    def test_coerce_kpi_date_values_counts_non_numeric(self):
        df = pd.DataFrame({"d1": ["1", "x", "3"], "d2": [4.0, 5.0, 6.0]})
        out, n_non_numeric = coerce_kpi_date_values(df, ["d1", "d2"])
        assert n_non_numeric == 1
        assert pd.isna(out.loc[1, "d1"])

    def test_build_kpi_pattern_wide_keeps_all_nan_as_nan(self):
        filtered = pd.DataFrame(
            {
                "region": ["A", "A", "B"],
                "d1": [1.0, np.nan, 5.0],
                "d2": [np.nan, np.nan, 6.0],
            }
        )
        wide = build_kpi_pattern_wide(filtered, "region", ["d1", "d2"])
        assert wide.loc["A", "d1"] == pytest.approx(1.0)
        assert np.isnan(wide.loc["A", "d2"])  # min_count=1: all-missing stays missing

    def test_retain_kpi_dates(self):
        wide_full = pd.DataFrame(
            {"d1": [1.0, 2.0, 0.0, np.nan], "d2": [3.0, 4.0, 0.0, 5.0]},
            index=pd.Index(["A", "B", "C", "D"], name="region"),
        )
        wide, incomplete = retain_kpi_dates(wide_full, ["d1", "d2"])
        # C is all-zero -> dropped; D has NaN -> incomplete but retained until index step
        assert list(wide.index) == ["A", "B", "D"]
        assert incomplete == ["D"]

    def test_build_kpi_pattern_agg_df(self):
        indexed = pd.DataFrame(
            {"20240101": [50.0, 100.0], "20240108": [150.0, 50.0]},
            index=pd.Index(["A", "B"], name="region"),
        )
        wide_raw = pd.DataFrame(
            {"20240101": [100.0, 10.0], "20240108": [200.0, 20.0]},
            index=pd.Index(["A", "B"], name="region"),
        )
        agg = build_kpi_pattern_agg_df(indexed, wide_raw, "geo", ["wk_20240101", "wk_20240108"])
        assert list(agg.columns) == ["geo", "wk_20240101", "wk_20240108", POPULATION_COL]
        assert agg[POPULATION_COL].tolist() == [300.0, 30.0]  # row sums of wide_raw

    def test_read_kpi_pattern_excel(self):
        buffer = io.BytesIO()
        pd.DataFrame({"region": ["A"], "20240101": [1.0]}).to_excel(buffer, index=False)
        buffer.seek(0)
        df = read_kpi_pattern_excel(buffer.getvalue())
        assert list(df.columns) == ["region", "20240101"]
        assert len(df) == 1
