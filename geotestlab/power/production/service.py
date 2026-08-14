"""Production power service over the canonical regional KPI contract."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from geotestlab.data import RegionalKPIDataset
from geotestlab.experiment import (
    ExperimentRecord,
    compute_input_fingerprint,
    record_stage_result,
    stage_is_stale,
    update_inputs,
)
from geotestlab.power.models import PowerConfig
from geotestlab.power.production.models import (
    APPROVED_EVIDENCE_COMMIT,
    APPROVED_METHODOLOGY_VERSION,
    PRODUCTION_POWER_CONTRACT_VERSION,
    ProductionPowerConfig,
    ProductionPowerResult,
    _date_value,
)
from geotestlab.power.service import run_power_analysis

_SUPPORTED_RESULT_STATUSES = {"supported", "supported_with_warning"}


def _normalise_dates(values: Iterable) -> tuple[pd.Timestamp, ...]:
    parsed = tuple(pd.to_datetime(list(values), errors="coerce", utc=False))
    if any(pd.isna(value) for value in parsed):
        raise ValueError("dates must all be parseable")
    return tuple(pd.Timestamp(value).normalize() for value in parsed)


def _validate_config(
    config: ProductionPowerConfig,
) -> tuple[pd.Timestamp, pd.Timestamp, tuple[pd.Timestamp, ...]]:
    if not config.method:
        raise ValueError("method is required; production power has no implicit method default")
    if not config.fit_method:
        raise ValueError("fit_method is required; production power has no implicit fit default")
    if not config.test_regions or not config.control_regions:
        raise ValueError("test_regions and control_regions are required")
    if len(set(config.test_regions)) != len(config.test_regions):
        raise ValueError("test_regions must not contain duplicates")
    if len(set(config.control_regions)) != len(config.control_regions):
        raise ValueError("control_regions must not contain duplicates")
    overlap = set(config.test_regions) & set(config.control_regions)
    if overlap:
        raise ValueError(f"regions cannot be both test and control: {sorted(overlap)}")

    start, end = _normalise_dates((config.historical_start, config.historical_end))
    if start > end:
        raise ValueError("historical_start must be on or before historical_end")
    test_dates = _normalise_dates(config.test_dates)
    if not test_dates:
        raise ValueError("test_dates must contain at least one planned test date")
    if len(set(test_dates)) != len(test_dates):
        raise ValueError("test_dates must not contain duplicates")
    if any(value <= end for value in test_dates):
        raise ValueError("test_dates must be after historical_end")
    if tuple(sorted(test_dates)) != test_dates:
        raise ValueError("test_dates must be sorted chronologically")

    effects = tuple(float(value) for value in config.target_effects)
    if not effects or any(not np.isfinite(value) or value < 0 for value in effects):
        raise ValueError("target_effects must contain finite non-negative values")
    if len(set(effects)) != len(effects):
        raise ValueError("target_effects must not contain duplicates")
    lower, upper = (float(config.mde_bounds[0]), float(config.mde_bounds[1]))
    if not np.isfinite([lower, upper]).all() or lower < 0 or upper <= lower:
        raise ValueError("mde_bounds must be finite, non-negative, and increasing")
    if any(value < lower or value > upper for value in effects):
        raise ValueError("target_effects must lie within mde_bounds")
    if config.effect_grid:
        grid = tuple(float(value) for value in config.effect_grid)
        if len(set(grid)) < 2 or any(not np.isfinite(value) for value in grid):
            raise ValueError("effect_grid must contain at least two finite unique values")
        if any(value < lower or value > upper for value in grid):
            raise ValueError("effect_grid must lie within mde_bounds")
        if any(value not in set(grid) for value in effects):
            raise ValueError("effect_grid must include every target_effect")
    if config.min_historical_periods <= 0 or config.n_simulations <= 0:
        raise ValueError("min_historical_periods and n_simulations must be positive")
    return start, end, test_dates


def _select_case(
    dataset: RegionalKPIDataset,
    config: ProductionPowerConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    test_dates: tuple[pd.Timestamp, ...],
) -> tuple[pd.DataFrame, str, tuple[pd.Timestamp, ...]]:
    if config.metric_value is None:
        if len(dataset.metrics) != 1:
            raise ValueError("metric_value is required when the dataset contains multiple metrics")
        metric = dataset.metrics[0]
    else:
        metric = str(config.metric_value)
        if metric not in dataset.metrics:
            raise ValueError(f"Metric {metric!r} is not present in the KPI dataset")

    frame = dataset.data[dataset.data["metric"].astype(str) == metric].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    pre_dates = tuple(sorted(frame.loc[frame["date"].between(start, end), "date"].unique()))
    if not pre_dates:
        raise ValueError("historical period contains no retained KPI dates")
    available_test_dates = set(frame["date"].dropna().unique())
    missing_test_dates = [date for date in test_dates if date not in available_test_dates]
    if missing_test_dates:
        raise ValueError(
            "planned test dates are not present in the canonical dataset: "
            + ", ".join(_date_value(value) for value in missing_test_dates)
        )
    selected_dates = set(pre_dates) | set(test_dates)
    case = frame[frame["date"].isin(selected_dates)][["region", "date", "kpi"]].copy()
    return case, metric, pre_dates


def production_input_fingerprint(dataset: RegionalKPIDataset, config: ProductionPowerConfig) -> str:
    """Fingerprint source identity plus every production power input."""

    return compute_input_fingerprint(
        {
            "contract": PRODUCTION_POWER_CONTRACT_VERSION,
            "methodology_version": APPROVED_METHODOLOGY_VERSION,
            "source_data_fingerprint": dataset.source_data_fingerprint,
            "config": config.to_dict(),
        }
    )


def production_result_is_stale(
    result: ProductionPowerResult,
    dataset: RegionalKPIDataset,
    config: ProductionPowerConfig,
) -> bool:
    """Return whether a result was produced under different power inputs."""

    return result.input_fingerprint != production_input_fingerprint(dataset, config)


def production_stage_is_stale(
    experiment_record: ExperimentRecord,
    dataset: RegionalKPIDataset,
    config: ProductionPowerConfig,
) -> bool:
    """Use the shared experiment staleness contract for statistical power."""

    return stage_is_stale(
        experiment_record,
        "statistical_power",
        production_input_fingerprint(dataset, config),
    )


def run_production_power(
    dataset: RegionalKPIDataset,
    config: ProductionPowerConfig,
    *,
    experiment_record: ExperimentRecord | None = None,
) -> ProductionPowerResult:
    """Run production power over one canonical dataset and explicit design.

    The underlying simulation implementation is deliberately called through
    the existing spike service, but this boundary owns the production input
    contract, provenance, metric/date selection, support semantics and
    experiment fingerprinting. It never adds media or effect-plausibility
    assumptions.
    """

    start, end, test_dates = _validate_config(config)
    case, metric, pre_dates = _select_case(dataset, config, start, end, test_dates)
    input_fingerprint = production_input_fingerprint(dataset, config)
    effect_grid = tuple(config.effect_grid)
    if not effect_grid:
        effect_grid = tuple(
            sorted(
                set(
                    (
                        float(config.mde_bounds[0]),
                        *config.target_effects,
                        float(config.mde_bounds[1]),
                    )
                )
            )
        )
    spike_config = PowerConfig(
        method=config.method,
        fit_method=config.fit_method,
        detection_criterion=config.detection_criterion,
        effect_injection=config.effect_injection,
        effect_shape=config.effect_shape,
        side=config.side,
        frequency=config.frequency,
        alpha=config.alpha,
        target_power=config.target_power,
        n_simulations=config.n_simulations,
        random_seed=config.random_seed,
        mde_bounds=tuple(config.mde_bounds),
        mde_tolerance=config.mde_tolerance,
        min_historical_periods=config.min_historical_periods,
        min_placebo_windows=config.min_placebo_windows,
        min_simulations=config.min_simulations,
        effect_grid=effect_grid,
        test_regions=tuple(config.test_regions),
        control_regions=tuple(config.control_regions),
        test_dates=test_dates,
    )
    spike_result = run_power_analysis(case, len(pre_dates), spike_config)
    result_effects = tuple(float(value) for value in spike_result.effect_grid)
    powers = tuple(float(value) for value in spike_result.power_curve)
    ci_lower = tuple(float(value) for value in spike_result.power_ci_lower)
    ci_upper = tuple(float(value) for value in spike_result.power_ci_upper)
    index_by_effect = {value: index for index, value in enumerate(result_effects)}
    target_indices = [index_by_effect[float(value)] for value in config.target_effects]
    target_powers = tuple(powers[index] for index in target_indices)
    target_ci = tuple((ci_lower[index], ci_upper[index]) for index in target_indices)
    safety = dict(spike_result.safety_diagnostics)
    support_status = str(spike_result.support_status)
    completed = bool(spike_result.completed)
    usable = completed and support_status in _SUPPORTED_RESULT_STATUSES
    historical_summary = {
        "frequency": config.frequency,
        "historical_start": _date_value(start),
        "historical_end": _date_value(end),
        "retained_periods": len(pre_dates),
        "minimum_periods": config.min_historical_periods,
        "minimum_history_status": spike_result.minimum_history_status,
        "source_quality_warnings": list(dataset.quality.warnings),
        "missing_dates": [_date_value(value) for value in dataset.quality.missing_dates],
    }
    result = ProductionPowerResult(
        production_contract_version=PRODUCTION_POWER_CONTRACT_VERSION,
        methodology_version=spike_result.methodology_version,
        evidence_commit=APPROVED_EVIDENCE_COMMIT,
        input_fingerprint=input_fingerprint,
        source_data_fingerprint=dataset.source_data_fingerprint,
        metric=metric,
        method=spike_result.method,
        fit_method=spike_result.fit_method,
        fit_status=str(spike_result.fit_status),
        detection_criterion=spike_result.detection_criterion,
        effect_injection=spike_result.effect_injection,
        effect_shape=spike_result.effect_shape,
        side=spike_result.side,
        frequency=spike_result.frequency,
        alpha=spike_result.alpha,
        target_power=spike_result.target_power,
        n_simulations=spike_result.n_simulations,
        random_seed=spike_result.random_seed,
        test_regions=tuple(config.test_regions),
        control_regions=tuple(config.control_regions),
        historical_start=_date_value(start),
        historical_end=_date_value(end),
        planned_test_dates=tuple(_date_value(value) for value in test_dates),
        target_effects=tuple(float(value) for value in config.target_effects),
        power_at_target_effects=target_powers,
        power_ci_at_target_effects=target_ci,
        effect_grid=result_effects,
        power_curve=powers,
        power_ci_lower=ci_lower,
        power_ci_upper=ci_upper,
        mde=float(spike_result.mde) if spike_result.mde is not None else None,
        mde_reached=bool(spike_result.mde_reached),
        mde_bounds=tuple(float(value) for value in spike_result.mde_bounds),
        uncertainty_kind="conditional_clopper_pearson",
        uncertainty_is_unconditional=False,
        effective_test_periods=spike_result.effective_test_periods,
        requested_test_periods=len(test_dates),
        windows_available=spike_result.windows_available,
        windows_used=spike_result.windows_used,
        fit_diagnostics=dict(spike_result.matrix_diagnostics),
        historical_data_sufficiency=historical_summary,
        support_status=support_status,
        safety_diagnostics=safety,
        safety_policy_version=spike_result.safety_policy_version,
        completed=completed,
        usable_for_recommendation=usable,
        warnings=tuple(spike_result.warnings),
        errors=tuple(spike_result.errors),
        blockers=tuple(spike_result.blockers),
        experiment_id=experiment_record.experiment_id if experiment_record else None,
    )
    if experiment_record is not None:
        update_inputs(
            experiment_record,
            input_fingerprint,
            {
                "stage": "statistical_power",
                "metric": metric,
                "source_data_fingerprint": dataset.source_data_fingerprint,
                "method": config.method,
                "fit_method": config.fit_method,
            },
        )
        record_stage_result(
            experiment_record,
            "statistical_power",
            input_fingerprint,
            status="completed" if completed else "in_progress",
        )
    return result
