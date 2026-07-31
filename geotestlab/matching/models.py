"""Immutable typed objects for the GeoTestLab matching core.

This module must not import Streamlit.  ``MatchConfig`` / ``FeatureWeightConfig``
are serialisable inputs; ``MatchConstraints`` is the one explicit constraint
model; ``MatchDiagnostics`` / ``MatchResult`` are serialisable outputs kept
separate from internal fitted objects (fitted models, metric arrays).
"""

from __future__ import annotations

from dataclasses import dataclass

# Shared column-name constants used across the matching core and the app.
POPULATION_COL = "Population"
POPULATION_COL_RAW = "Total Population"
ADOBE_COL = "Adobe Reference List"


@dataclass(frozen=True)
class MatchConfig:
    """Typed matching configuration.

    Defaults mirror the app's historical ``CONFIG`` values so the package is
    self-contained; the live app passes its own instance (or the defaults).
    """

    max_hill_climbing_swaps: int = 15
    max_control_pool_size: int = 50
    genetic_iterations_min: int = 100
    genetic_iterations_max: int = 5000
    genetic_iterations_default: int = 1000
    smd_good_threshold: float = 0.20
    smd_high_threshold: float = 0.50
    seed: int = 42


@dataclass(frozen=True)
class FeatureWeightConfig:
    """Typed per-feature weight configuration (serialisable).

    Stored as an ordered tuple of (feature, weight) pairs so it survives
    JSON/pickle round-trips; ``to_dict()`` gives the dict form the matching
    functions accept.
    """

    weights: tuple[tuple[str, float], ...] = ()

    @classmethod
    def from_dict(cls, weights: dict) -> FeatureWeightConfig:
        return cls(tuple((str(k), float(v)) for k, v in weights.items()))

    def to_dict(self) -> dict[str, float]:
        return dict(self.weights)


@dataclass(frozen=True)
class MatchConstraints:
    """One explicit, typed constraint model for 'Set Rules & Auto-Build Groups'.

    A region may be assigned to at most ONE field.  ``validate_constraints()``
    (see ``constraints.py``) is the single authority for detecting contradictory
    overlaps — widget option subtraction is a convenience, never the only
    conflict-prevention mechanism.
    """

    exclude_from_both: tuple[str, ...] = ()
    force_test_include: tuple[str, ...] = ()
    test_only_exclude: tuple[str, ...] = ()
    force_control_include: tuple[str, ...] = ()
    control_only_exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchDiagnostics:
    """Serialisable summary of a matching run.

    Kept separate from internal fitted objects (fitted models, metric arrays):
    this is what run snapshots / exports / future fingerprints record.
    """

    strategy: str
    weighted_structural_distance: float | None = None
    mean_abs_smd: float | None = None
    control_group_size: int = 0
    test_group_size: int = 0
    seed: int | None = None
    candidates_evaluated: int = 0
    convergence: tuple[float, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    """Serialisable outcome of a matching run for one control-group size.

    ``control_indices`` are the pool index labels selected as controls;
    headline metrics are recorded here; the full per-feature metric dict stays
    internal to the strategy caller.
    """

    strategy: str
    control_indices: tuple[str | int, ...] = ()
    weighted_structural_distance: float | None = None
    mean_abs_smd: float | None = None
    smd_list: tuple[float, ...] = ()
    candidates_evaluated: int = 0
    convergence: tuple[float, ...] = ()
    seed: int | None = None
