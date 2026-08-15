"""Tests for the approved production power boundary."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import geotestlab.power.production.service as production_service
from geotestlab.data import RegionalKPIConfig, prepare_regional_kpi
from geotestlab.experiment import create_experiment_record
from geotestlab.power.production import (
    APPROVED_METHODOLOGY_VERSION,
    ProductionPowerConfig,
    production_input_fingerprint,
    production_result_is_stale,
    production_stage_is_stale,
    run_production_power,
)


def _dataset(metrics: tuple[str, ...] = ("Sales",)):
    dates = pd.date_range("2024-01-07", periods=112, freq="7D")
    rng = np.random.default_rng(1234)
    control = 100.0 + rng.normal(0.0, 1.0, len(dates))
    test = 10.0 + 1.15 * control + rng.normal(0.0, 0.4, len(dates))
    frame = pd.DataFrame(
        {
            "Region": ["Test", "Control"],
            "Metric": ["Sales", "Sales"],
            **{
                date: [test_value, control_value]
                for date, test_value, control_value in zip(dates, test, control)
            },
        }
    )
    if len(metrics) > 1:
        extra = frame.copy()
        extra["Metric"] = metrics[1]
        frame = pd.concat([frame, extra], ignore_index=True)
    return prepare_regional_kpi(frame, RegionalKPIConfig())


def _config(**overrides) -> ProductionPowerConfig:
    dates = pd.date_range("2024-01-07", periods=112, freq="7D")
    values = {
        "method": "model_simulation",
        "fit_method": "ols",
        "test_regions": ("Test",),
        "control_regions": ("Control",),
        "historical_start": dates[0],
        "historical_end": dates[103],
        "historical_holdout_dates": tuple(dates[104:]),
        "planned_duration_periods": 8,
        "target_effects": (5.0,),
        "mde_bounds": (0.0, 10.0),
        "n_simulations": 100,
        "random_seed": 19,
    }
    values.update(overrides)
    return ProductionPowerConfig(**values)


def test_production_run_uses_canonical_data_and_records_experiment_stage():
    dataset = _dataset()
    record = create_experiment_record(now=pd.Timestamp("2026-08-14", tz="UTC").to_pydatetime())

    result = run_production_power(dataset, _config(), experiment_record=record)

    assert result.methodology_version == APPROVED_METHODOLOGY_VERSION
    assert result.metric == "Sales"
    assert result.test_regions == ("Test",)
    assert result.control_regions == ("Control",)
    assert result.requested_test_periods == 8
    assert result.planned_duration_periods == 8
    assert len(result.historical_holdout_dates) == 8
    assert result.planned_test_dates == ()
    assert len(result.power_at_target_effects) == 1
    assert len(result.power_ci_at_target_effects) == 1
    assert result.input_fingerprint == record.stage_fingerprints["statistical_power"]
    assert record.stage_status["statistical_power"] in {"completed", "in_progress"}
    assert production_result_is_stale(result, dataset, _config()) is False
    assert production_stage_is_stale(record, dataset, _config()) is False
    assert production_result_is_stale(result, dataset, _config(random_seed=20)) is True
    json.dumps(result.to_dict())


def test_production_fingerprint_changes_when_design_changes():
    dataset = _dataset()

    first = production_input_fingerprint(dataset, _config())
    changed = production_input_fingerprint(dataset, _config(random_seed=20))
    duration_changed = production_input_fingerprint(
        dataset,
        _config(
            historical_holdout_dates=_config().historical_holdout_dates[:-1],
            planned_duration_periods=7,
        ),
    )

    assert first.startswith("fp1:")
    assert changed != first
    assert duration_changed != first


def test_metric_must_be_explicit_for_multiple_metrics():
    dataset = _dataset(("Sales", "Orders"))

    with pytest.raises(ValueError, match="metric_value is required"):
        run_production_power(dataset, _config())


def test_missing_historical_holdout_date_is_rejected():
    dataset = _dataset()
    missing_date = pd.date_range("2024-01-07", periods=112, freq="7D")[-1]
    dataset = replace(dataset, data=dataset.data[dataset.data["date"] != missing_date])
    config = _config()

    with pytest.raises(ValueError, match="historical holdout dates are not present"):
        run_production_power(dataset, config)


def test_future_campaign_dates_are_metadata_and_do_not_need_source_observations(
    monkeypatch,
):
    dataset = _dataset()
    dates = pd.date_range("2024-01-07", periods=112, freq="7D")
    planned_dates = pd.date_range("2027-01-03", periods=4, freq="7D")
    config = _config(
        historical_holdout_dates=tuple(dates[104:108]),
        planned_duration_periods=4,
        planned_test_dates=tuple(planned_dates),
    )
    captured = {}
    original_select_case = production_service._select_case

    def capture_case(*args, **kwargs):
        case, metric, pre_dates = original_select_case(*args, **kwargs)
        captured["dates"] = set(pd.to_datetime(case["date"]).dt.normalize())
        return case, metric, pre_dates

    monkeypatch.setattr(production_service, "_select_case", capture_case)
    result = run_production_power(dataset, config)

    assert result.planned_test_dates == tuple(value.isoformat() for value in planned_dates)
    assert result.historical_holdout_dates == tuple(value.isoformat() for value in dates[104:108])
    assert result.requested_test_periods == 4
    assert set(pd.to_datetime(planned_dates).normalize()).isdisjoint(captured["dates"])
    assert result.historical_data_sufficiency["planned_schedule_provided"] is True
    assert result.to_dict()["planned_test_dates"] == [value.isoformat() for value in planned_dates]


def test_holdout_continuity_and_duration_are_enforced():
    dates = pd.date_range("2024-01-07", periods=112, freq="7D")

    with pytest.raises(ValueError, match="historical_holdout_dates must be contiguous"):
        run_production_power(
            _dataset(),
            _config(
                historical_holdout_dates=tuple(dates[104:106]) + tuple(dates[107:109]),
                planned_duration_periods=4,
            ),
        )

    with pytest.raises(ValueError, match="exactly planned_duration_periods"):
        run_production_power(
            _dataset(),
            _config(
                historical_holdout_dates=tuple(dates[104:108]),
                planned_duration_periods=5,
            ),
        )


def test_production_config_has_no_implicit_method_or_fit_default():
    fields = ProductionPowerConfig.__dataclass_fields__

    assert fields["method"].default.__class__.__name__ == "_MISSING_TYPE"
    assert fields["fit_method"].default.__class__.__name__ == "_MISSING_TYPE"
