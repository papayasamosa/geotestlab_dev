"""Guided 'Set Rules & Auto-Build Groups' search: typed constraint model,
conflict validation, and the deterministic guided test-group search.

Pure functions (no Streamlit).  ``MatchConstraints`` lives in ``models.py``;
``ConstraintConflict`` and ``validate_constraints`` are the single authority
for detecting contradictory overlaps.  ``find_guided_test_group`` takes an
injected ``numpy.random.Generator`` for reproducibility and uses ``sorted()``
on set-derived candidate lists so results are identical across processes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import POPULATION_COL, MatchConstraints


@dataclass(frozen=True)
class GuidedSearchConfig:
    """Typed configuration for the guided 'Set Rules & Auto-Build Groups' search.

    ``seed`` makes the stochastic guided search reproducible: the caller builds
    a ``numpy.random.Generator`` from it and injects it into
    ``find_guided_test_group()``.  The seed is recorded in run snapshots,
    exports, input fingerprints, and the numerical golden settings.
    """

    seed: int = 42
    search_iterations_default: int = 2000
    target_share_default: int = 25
    tolerance_pp_default: int = 5


GUIDED_SEARCH_CONFIG = GuidedSearchConfig()


@dataclass(frozen=True)
class ConstraintConflict:
    """Structured overlap error: a region assigned to more than one field."""

    region: str
    fields: tuple[str, ...]


def validate_constraints(constraints: MatchConstraints) -> tuple[ConstraintConflict, ...]:
    """Return one structured ConstraintConflict per region with a CONTRADICTORY
    assignment.

    The one-sided exclusion semantics remain valid: a region assigned to
    ``test_only_exclude`` AND ``force_control_include`` is simply
    'control-only' (consistent), and ``force_test_include`` +
    ``control_only_exclude`` is 'test-only' (consistent).  Only contradictory
    assignments are conflicts:
    - ``exclude_from_both`` combined with any other field;
    - ``force_test_include`` with ``test_only_exclude``;
    - ``force_test_include`` with ``force_control_include``;
    - ``force_control_include`` with ``control_only_exclude``.

    Pure function — no Streamlit dependency.
    """
    field_regions: dict[str, tuple[str, ...]] = {
        "exclude_from_both": constraints.exclude_from_both,
        "force_test_include": constraints.force_test_include,
        "test_only_exclude": constraints.test_only_exclude,
        "force_control_include": constraints.force_control_include,
        "control_only_exclude": constraints.control_only_exclude,
    }
    region_to_fields: dict[str, list[str]] = {}
    for field, regions in field_regions.items():
        for region in regions:
            region_to_fields.setdefault(region, []).append(field)

    def _is_conflicting(fields: list[str]) -> bool:
        field_set = set(fields)
        if "exclude_from_both" in field_set and len(field_set) > 1:
            return True
        if {"force_test_include", "force_control_include"} <= field_set:
            return True
        if {"force_test_include", "test_only_exclude"} <= field_set:
            return True
        if {"force_control_include", "control_only_exclude"} <= field_set:
            return True
        return False

    return tuple(
        ConstraintConflict(region=region, fields=tuple(fields))
        for region, fields in sorted(region_to_fields.items())
        if _is_conflicting(fields)
    )


def find_guided_test_group(
    agg_df,
    geo_col,
    total_market_pop,
    force_exp_include,
    force_exp_exclude,
    force_ctrl_include,
    force_ctrl_exclude,
    target_share,
    tolerance_pp,
    search_iterations=2000,
    rng=None,
):
    """Search for a test group satisfying the guided-share constraints.

    ``rng`` is an injected ``numpy.random.Generator`` — the caller controls
    reproducibility (see ``GuidedSearchConfig.seed``).  No module-global
    ``random`` state is used.  Returns (best_set, best_share, met).
    """
    if rng is None:
        rng = np.random.default_rng(GUIDED_SEARCH_CONFIG.seed)
    all_geos = set(agg_df[geo_col].unique())
    forced_test = set(force_exp_include)
    # Exclusions are one-sided: force_ctrl_exclude removes a region from the
    # CONTROL pool only — it remains a valid TEST candidate (and vice versa for
    # force_exp_exclude, which is handled in the control-pool construction).
    # To drop a region from the analysis entirely, it must be excluded from
    # BOTH lists. Control-side INCLUDES are barred from test because a region
    # can belong to only one group.
    forbidden_test = set(force_exp_exclude) | set(force_ctrl_include)
    # sorted() keeps the candidate list order deterministic across processes —
    # Python string-set iteration order is randomized per process, and the rng
    # picks candidates by index.
    candidate = sorted(all_geos - forced_test - forbidden_test)
    pop_map = agg_df.set_index(geo_col)[POPULATION_COL].to_dict()
    if any(g not in all_geos for g in forced_test):
        return [], 0, False
    forced_pop = sum(pop_map.get(g, 0) for g in forced_test)
    low = max(0, target_share - tolerance_pp) / 100
    high = min(100, target_share + tolerance_pp) / 100
    best_set = sorted(forced_test)
    best_share = (forced_pop / total_market_pop) if total_market_pop > 0 else 0
    best_dist = (
        min(abs(best_share - low), abs(best_share - high)) if not (low <= best_share <= high) else 0
    )
    met = low <= best_share <= high
    if len(candidate) <= 16:
        from itertools import combinations

        for r in range(len(candidate) + 1):
            for comb in combinations(candidate, r):
                trial = sorted(forced_test | set(comb))
                share = (
                    agg_df[agg_df[geo_col].isin(trial)][POPULATION_COL].sum() / total_market_pop
                    if total_market_pop > 0
                    else 0
                )
                d = 0 if (low <= share <= high) else min(abs(share - low), abs(share - high))
                if (d < best_dist) or (
                    d == best_dist
                    and abs(share - (target_share / 100)) < abs(best_share - (target_share / 100))
                ):
                    best_set, best_share, best_dist = trial, share, d
                    met = low <= share <= high
    else:
        for _ in range(search_iterations):
            k = int(rng.integers(0, len(candidate) + 1))
            sampled = [candidate[i] for i in rng.choice(len(candidate), size=k, replace=False)]
            trial = sorted(forced_test | set(sampled))
            share = (
                agg_df[agg_df[geo_col].isin(trial)][POPULATION_COL].sum() / total_market_pop
                if total_market_pop > 0
                else 0
            )
            d = 0 if (low <= share <= high) else min(abs(share - low), abs(share - high))
            if (d < best_dist) or (
                d == best_dist
                and abs(share - (target_share / 100)) < abs(best_share - (target_share / 100))
            ):
                best_set, best_share, best_dist = trial, share, d
                met = low <= share <= high
    return best_set, best_share, met
