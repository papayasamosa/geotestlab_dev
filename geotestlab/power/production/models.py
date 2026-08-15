"""Typed production power inputs and outputs.

This contract deliberately has no implicit simulation-method default. The
approved methodology records both candidate simulation paths and requires the
caller to choose and persist the method and fit method explicitly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from geotestlab.power.models import METHODOLOGY_VERSION

PRODUCTION_POWER_CONTRACT_VERSION = "1.1.0"
APPROVED_METHODOLOGY_VERSION = METHODOLOGY_VERSION
APPROVED_EVIDENCE_COMMIT = "6380c46d124535baa6702341d0ce02f6d2fe5478"


def _date_value(value: Any) -> str:
    """Return a stable ISO date/time representation for fingerprints/exports."""

    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True)
class ProductionPowerConfig:
    """Explicit inputs for one production statistical-power calculation."""

    # These fields are intentionally required: ADR-001 forbids an implicit
    # primary method, and a production result must name its design.
    method: str
    fit_method: str
    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    historical_start: Any
    historical_end: Any
    historical_holdout_dates: tuple[Any, ...]
    planned_duration_periods: int
    target_effects: tuple[float, ...]

    # Campaign dates are metadata only. They are deliberately optional because
    # the campaign may not have been scheduled yet and are never required to
    # exist in the historical KPI source.
    planned_test_dates: tuple[Any, ...] = ()
    detection_criterion: str = "interval_excludes_zero"
    effect_injection: str = "relative"
    effect_shape: str = "step"
    side: str = "one_sided_positive"
    frequency: str = "weekly"
    alpha: float = 0.05
    target_power: float = 0.80
    n_simulations: int = 1000
    random_seed: int = 42
    mde_bounds: tuple[float, float] = (0.0, 50.0)
    mde_tolerance: float = 0.5
    min_historical_periods: int = 104
    min_placebo_windows: int = 5
    min_simulations: int = 100
    metric_value: str | None = None
    effect_grid: tuple[float, ...] = ()

    def to_dict(self) -> dict:
        """Return JSON-safe configuration values for audit/fingerprints."""

        values = asdict(self)
        values["historical_start"] = _date_value(self.historical_start)
        values["historical_end"] = _date_value(self.historical_end)
        values["historical_holdout_dates"] = [
            _date_value(value) for value in self.historical_holdout_dates
        ]
        values["planned_test_dates"] = [
            _date_value(value) for value in self.planned_test_dates
        ]
        values["test_regions"] = list(self.test_regions)
        values["control_regions"] = list(self.control_regions)
        values["target_effects"] = [float(value) for value in self.target_effects]
        values["effect_grid"] = [float(value) for value in self.effect_grid]
        values["mde_bounds"] = [float(value) for value in self.mde_bounds]
        return values


@dataclass(frozen=True)
class ProductionPowerResult:
    """Auditable result of a production power calculation."""

    production_contract_version: str
    methodology_version: str
    evidence_commit: str
    input_fingerprint: str
    source_data_fingerprint: str
    metric: str
    method: str
    fit_method: str
    fit_status: str
    detection_criterion: str
    effect_injection: str
    effect_shape: str
    side: str
    frequency: str
    alpha: float
    target_power: float
    n_simulations: int
    random_seed: int
    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    historical_start: str
    historical_end: str
    planned_test_dates: tuple[str, ...]
    target_effects: tuple[float, ...]
    power_at_target_effects: tuple[float, ...]
    power_ci_at_target_effects: tuple[tuple[float, float], ...]
    effect_grid: tuple[float, ...]
    power_curve: tuple[float, ...]
    power_ci_lower: tuple[float, ...]
    power_ci_upper: tuple[float, ...]
    mde: float | None
    mde_reached: bool
    mde_bounds: tuple[float, float]
    uncertainty_kind: str
    uncertainty_is_unconditional: bool
    effective_test_periods: int
    requested_test_periods: int
    windows_available: int
    windows_used: int
    historical_holdout_dates: tuple[str, ...] = ()
    planned_duration_periods: int = 0
    fit_diagnostics: dict = field(default_factory=dict)
    historical_data_sufficiency: dict = field(default_factory=dict)
    support_status: str = "not_applicable"
    safety_diagnostics: dict = field(default_factory=dict)
    safety_policy_version: str = ""
    completed: bool = False
    usable_for_recommendation: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    experiment_id: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-safe export without numpy or pandas objects."""

        result = asdict(self)
        result["test_regions"] = list(self.test_regions)
        result["control_regions"] = list(self.control_regions)
        result["planned_test_dates"] = list(self.planned_test_dates)
        result["historical_holdout_dates"] = list(self.historical_holdout_dates)
        result["target_effects"] = [float(value) for value in self.target_effects]
        result["power_at_target_effects"] = [float(value) for value in self.power_at_target_effects]
        result["power_ci_at_target_effects"] = [
            list(interval) for interval in self.power_ci_at_target_effects
        ]
        result["effect_grid"] = [float(value) for value in self.effect_grid]
        result["power_curve"] = [float(value) for value in self.power_curve]
        result["power_ci_lower"] = [float(value) for value in self.power_ci_lower]
        result["power_ci_upper"] = [float(value) for value in self.power_ci_upper]
        result["mde_bounds"] = [float(value) for value in self.mde_bounds]
        return result
