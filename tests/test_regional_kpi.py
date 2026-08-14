"""Tests for the canonical regional KPI preparation contract."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from geotestlab.data import (
    MarketSizeMeasure,
    RegionalKPIConfig,
    prepare_regional_kpi,
    regional_kpi_to_validation_frame,
    regional_kpi_to_wide,
)
from geotestlab.matching.kpi_pattern import build_kpi_pattern_wide_from_regional

DATES = pd.to_datetime(["2026-01-04", "2026-01-11", "2026-01-18"])


def _simple_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Region": ["A", "B"],
            "Metric": ["Sales", "Sales"],
            DATES[0]: [10.0, 20.0],
            DATES[1]: [11.0, 21.0],
            DATES[2]: [12.0, 22.0],
        }
    )


def _aggregated_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Raw Key": ["a1", "a2", "b1"],
            "Country": ["SE", "SE", "SE"],
            "Region": ["North", "North", "South"],
            "Metric": ["Sales", "Sales", "Sales"],
            DATES[0]: [1.0, 2.0, 10.0],
            DATES[1]: [np.nan, 3.0, 11.0],
            DATES[2]: [4.0, np.nan, 12.0],
        }
    )


def test_simple_layout_produces_canonical_long_data():
    dataset = prepare_regional_kpi(_simple_frame(), RegionalKPIConfig())

    assert {"region", "date", "metric", "kpi", "selected_aggregation"}.issubset(
        dataset.data.columns
    )
    assert dataset.data[["region", "metric", "date"]].duplicated().sum() == 0
    assert dataset.data["source_data_fingerprint"].nunique() == 1
    assert dataset.config.aggregation_column == "Region"
    assert dataset.config.metric_column == "Metric"
    assert dataset.quality.selected_layout == "simple"


def test_string_date_headers_are_detected():
    frame = pd.DataFrame(
        {
            "Region": ["A"],
            "Metric": ["Sales"],
            "2026-01-04": [10.0],
            "2026-01-11": [11.0],
        }
    )
    dataset = prepare_regional_kpi(frame, RegionalKPIConfig())

    assert dataset.quality.source_date_columns == 2
    assert set(dataset.data["date"]) == set(pd.to_datetime(["2026-01-04", "2026-01-11"]))


def test_multiple_classifications_use_selected_level_and_keep_provenance():
    dataset = prepare_regional_kpi(
        _aggregated_frame(),
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )

    assert set(dataset.data["region"]) == {"North", "South"}
    assert set(dataset.data["selected_aggregation"]) == {"Region"}
    assert {"Raw Key", "Country", "source_row_position"}.issubset(dataset.provenance.columns)
    assert set(dataset.provenance["region"]) == {"North", "South"}


def test_multiple_raw_rows_are_summed_with_min_count_one():
    dataset = prepare_regional_kpi(
        _aggregated_frame(),
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )
    wide = regional_kpi_to_wide(dataset, metric_value="Sales")

    assert wide.loc["North", DATES[0]] == pytest.approx(3.0)
    assert wide.loc["North", DATES[1]] == pytest.approx(3.0)
    assert wide.loc["North", DATES[2]] == pytest.approx(4.0)
    assert wide.loc["South", DATES[0]] == pytest.approx(10.0)


def test_multiple_metrics_can_be_retained_or_selected():
    frame = _simple_frame()
    frame.loc[len(frame)] = ["A", "Orders", 2.0, 3.0, 4.0]
    dataset = prepare_regional_kpi(frame, RegionalKPIConfig())

    assert set(dataset.metrics) == {"Sales", "Orders"}
    selected = dataset.for_metric("Orders")
    assert set(selected.data["metric"]) == {"Orders"}
    assert selected.data["kpi"].sum() == pytest.approx(9.0)


def test_blank_classification_is_excluded_and_reported():
    frame = _aggregated_frame()
    frame.loc[len(frame)] = ["blank", "SE", "", "Sales", 100.0, 100.0, 100.0]
    dataset = prepare_regional_kpi(
        frame,
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )

    assert "" not in set(dataset.data["region"])
    assert dataset.quality.source_rows_dropped_blank_region == 1
    assert any("blank" in warning.lower() for warning in dataset.quality.warnings)


def test_missing_dates_and_missing_cells_are_not_turned_into_zero():
    extra_date = pd.Timestamp("2026-01-25")
    frame = _simple_frame()
    frame[extra_date] = [13.0, 23.0]
    frame = frame.drop(columns=[DATES[1]])
    frame.loc[0, DATES[2]] = np.nan
    dataset = prepare_regional_kpi(frame, RegionalKPIConfig())

    assert dataset.quality.missing_dates == (DATES[1],)
    wide = regional_kpi_to_wide(dataset, metric_value="Sales")
    assert DATES[1] not in wide.columns
    assert pd.isna(wide.loc["A", DATES[2]])


def test_non_numeric_kpi_is_missing_and_reported():
    frame = _simple_frame()
    frame[DATES[1]] = frame[DATES[1]].astype(object)
    frame.loc[0, DATES[1]] = "not numeric"
    dataset = prepare_regional_kpi(frame, RegionalKPIConfig())

    assert dataset.quality.observations_dropped_non_numeric_kpi == 1
    assert pd.isna(regional_kpi_to_wide(dataset, "Sales").loc["A", DATES[1]])


def test_duplicate_source_analytical_keys_are_detected_before_aggregation():
    frame = _aggregated_frame()
    duplicate = frame.iloc[[0]].copy()
    frame = pd.concat([frame, duplicate], ignore_index=True)
    dataset = prepare_regional_kpi(
        frame,
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )

    assert dataset.quality.duplicate_analytical_key_rows == 2
    assert dataset.quality.duplicate_analytical_key_groups == 1
    assert any("analytical key" in warning.lower() for warning in dataset.quality.warnings)


def test_canonical_output_and_source_fingerprint_are_row_order_invariant():
    frame = _aggregated_frame()
    left = prepare_regional_kpi(
        frame,
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )
    right = prepare_regional_kpi(
        frame.sample(frac=1, random_state=17).reset_index(drop=True),
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )

    pd.testing.assert_frame_equal(left.data, right.data)
    assert left.source_data_fingerprint == right.source_data_fingerprint


def test_source_fingerprint_changes_when_source_values_change():
    original = prepare_regional_kpi(_simple_frame(), RegionalKPIConfig())
    changed_frame = _simple_frame()
    changed_frame.loc[0, DATES[0]] = 999.0
    changed = prepare_regional_kpi(changed_frame, RegionalKPIConfig())

    assert original.source_data_fingerprint != changed.source_data_fingerprint


def test_matching_validation_and_future_power_adapters_share_the_same_series():
    dataset = prepare_regional_kpi(
        _aggregated_frame(),
        RegionalKPIConfig(aggregation_column="Region", metric_column="Metric"),
    )
    expected = regional_kpi_to_wide(dataset, "Sales")

    matching_wide = build_kpi_pattern_wide_from_regional(dataset, "Sales", list(DATES))
    validation = regional_kpi_to_validation_frame(dataset, "Sales")
    future_power = dataset.for_metric("Sales").data

    pd.testing.assert_frame_equal(expected, matching_wide)
    pd.testing.assert_frame_equal(
        validation.sort_values(["region", "date"]).reset_index(drop=True),
        future_power[["region", "date", "kpi"]]
        .sort_values(["region", "date"])
        .reset_index(drop=True),
        check_dtype=False,
    )


def test_market_size_measure_is_explicit_and_uses_kpi_volume_not_region_count():
    dataset = prepare_regional_kpi(
        _aggregated_frame(),
        RegionalKPIConfig(
            aggregation_column="Region",
            metric_column="Metric",
            market_size_measure=MarketSizeMeasure.HISTORICAL_KPI_VOLUME,
        ),
    )
    weights = dataset.market_size_weights("Sales")

    assert weights.loc["North"] == pytest.approx(10.0)
    assert weights.loc["South"] == pytest.approx(33.0)
    assert weights.sum() == pytest.approx(43.0)
    assert dataset.config.market_size_measure is MarketSizeMeasure.HISTORICAL_KPI_VOLUME
