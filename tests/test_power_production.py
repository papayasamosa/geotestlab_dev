"""Tests for the approved production power boundary."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

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
        "test_dates": tuple(dates[104:]),
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

    assert first.startswith("fp1:")
    assert changed != first


def test_metric_must_be_explicit_for_multiple_metrics():
    dataset = _dataset(("Sales", "Orders"))

    with pytest.raises(ValueError, match="metric_value is required"):
        run_production_power(dataset, _config())


def test_missing_planned_test_date_is_rejected():
    dataset = _dataset()
    config = _config(test_dates=_config().test_dates[:-1] + (pd.Timestamp("2026-04-05"),))

    with pytest.raises(ValueError, match="not present"):
        run_production_power(dataset, config)


def test_production_config_has_no_implicit_method_or_fit_default():
    fields = ProductionPowerConfig.__dataclass_fields__

    assert fields["method"].default.__class__.__name__ == "_MISSING_TYPE"
    assert fields["fit_method"].default.__class__.__name__ == "_MISSING_TYPE"
