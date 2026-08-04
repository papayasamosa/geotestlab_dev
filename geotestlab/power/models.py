"""Typed models for the Stage 5 power-analysis methodology spike.

This is a *spike* prototype: it exists to produce decision evidence for the
approved prospective power-analysis product (see
``docs/product/power-analysis-and-test-sizing.md``). It is NOT the production
power engine and must not be extended into one without an approved
methodology decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Candidate first-release methods (PA-FR2).
METHODS = ("model_simulation", "placebo_empirical", "residual_simulation")

# Detection criteria (PA-FR4).
DETECTION_CRITERIA = ("interval_excludes_zero", "empirical_placebo_threshold", "sign_and_threshold")

# Effect injection policies (PA-FR3).
EFFECT_INJECTIONS = ("relative", "absolute")

# Effect shapes.
EFFECT_SHAPES = ("step", "ramp")

# Test sides.
SIDES = ("one_sided_positive", "one_sided_negative", "two_sided")

# Methodology version for the corrected spike contract (bumped when the result
# contract or methodology rule set changes).
METHODOLOGY_VERSION = "0.2.0"


def validate_effect_shape(shape: str) -> None:
    """Validate the effect shape for the spike service.

    Only ``step`` is implemented in the spike's simulation path. ``ramp`` exists
    only in the synthetic generator (fixtures) and must be rejected by the
    service until a real ramp simulation path is implemented.
    """
    if shape != "step":
        raise ValueError(
            f"effect_shape={shape!r} is not implemented in the spike service; "
            "only 'step' is supported. 'ramp' exists only in the synthetic "
            "generator for fixtures until a real ramp simulation path exists."
        )


@dataclass(frozen=True)
class PowerConfig:
    """Settings for one power-analysis run (spike prototype)."""

    method: str = "model_simulation"
    detection_criterion: str = "interval_excludes_zero"
    effect_injection: str = "relative"
    effect_shape: str = "step"
    side: str = "one_sided_positive"
    alpha: float = 0.05
    target_power: float = 0.80
    n_simulations: int = 1000
    random_seed: int = 42
    # MDE search bounds and tolerance (PA-FR6). Bounds in % (relative) or
    # absolute units; tolerance in the same units.
    mde_bounds: tuple = (0.0, 50.0)
    mde_tolerance: float = 0.5
    min_historical_periods: int = 12
    min_placebo_windows: int = 5
    min_simulations: int = 100
    # Counterfactual fit method (PA-FR2 evidence): ols | elastic_net | lasso.
    fit_method: str = "ols"
    # Explicit selected design (PA-FR2): required. The spike must not assume
    # one region is test and every other region is control.
    test_regions: tuple = ()
    control_regions: tuple = ()
    # Optional explicit planned test dates. When empty, the test window is the
    # dates after the pre-period (pre_count).
    test_dates: tuple = ()


@dataclass
class PowerResult:
    """Typed spike result with every PA-FR5 output recorded."""

    method: str
    detection_criterion: str
    effect_injection: str
    effect_shape: str
    side: str
    alpha: float
    target_power: float
    n_simulations: int
    random_seed: int
    effect_grid: np.ndarray
    power_curve: np.ndarray
    power_ci_lower: np.ndarray
    power_ci_upper: np.ndarray
    null_threshold: float
    null_mean: float = 0.0
    null_sd: float = 0.0
    mde: float | None = None
    mde_reached: bool = False
    mde_bounds: tuple = (0.0, 0.0)
    windows_available: int = 0
    windows_used: int = 0
    failures: int = 0
    warnings: tuple = field(default_factory=tuple)
    # Structured completion / fit / policy contract (PA-FR5). Critical states
    # are represented by these fields, not only by warning strings.
    completed: bool = False
    fit_status: str = "not_run"  # "ok" | "fallback_constant_mean" | "not_run"
    fit_method: str = ""  # "ols" | "elastic_net" | "lasso" | "constant_mean" | method
    matrix_diagnostics: dict = field(default_factory=dict)
    calibration_simulations: int = 0
    detection_simulations: int = 0
    minimum_history_status: str = "not_applicable"  # "ok" | "insufficient"
    minimum_window_status: str = "not_applicable"  # "ok" | "insufficient"
    methodology_version: str = METHODOLOGY_VERSION
    errors: tuple = field(default_factory=tuple)
    blockers: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """JSON-safe dict for the spike report."""
        return {
            "method": self.method,
            "detection_criterion": self.detection_criterion,
            "effect_injection": self.effect_injection,
            "effect_shape": self.effect_shape,
            "side": self.side,
            "alpha": self.alpha,
            "target_power": self.target_power,
            "n_simulations": self.n_simulations,
            "random_seed": self.random_seed,
            "effect_grid": [float(v) for v in self.effect_grid],
            "power_curve": [float(v) for v in self.power_curve],
            "power_ci_lower": [float(v) for v in self.power_ci_lower],
            "power_ci_upper": [float(v) for v in self.power_ci_upper],
            "null_threshold": float(self.null_threshold),
            "null_mean": float(self.null_mean),
            "null_sd": float(self.null_sd),
            "mde": float(self.mde) if self.mde is not None else None,
            "mde_reached": bool(self.mde_reached),
            "mde_bounds": [float(v) for v in self.mde_bounds],
            "windows_available": int(self.windows_available),
            "windows_used": int(self.windows_used),
            "failures": int(self.failures),
            "warnings": list(self.warnings),
            "completed": bool(self.completed),
            "fit_status": self.fit_status,
            "fit_method": self.fit_method,
            "matrix_diagnostics": dict(self.matrix_diagnostics),
            "calibration_simulations": int(self.calibration_simulations),
            "detection_simulations": int(self.detection_simulations),
            "minimum_history_status": self.minimum_history_status,
            "minimum_window_status": self.minimum_window_status,
            "methodology_version": self.methodology_version,
            "errors": list(self.errors),
            "blockers": list(self.blockers),
        }
