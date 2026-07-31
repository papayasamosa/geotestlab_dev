"""Pure tests for guided-search determinism and the constraint model (Stage 3).

The matching core still lives inside ``geotestmatch.py`` (extraction is
Stage 4), so these tests load the exact production symbols via AST — as
``tests/test_text_cleaning.py`` does — without launching the Streamlit app.

Desired corrected behaviour (fails on the current unseeded / untyped code):
- ``find_guided_test_group`` accepts an injected ``numpy.random.Generator``;
  identical inputs + seed produce identical groups; a different seed can
  produce a different (still valid) group.
- constraints are one explicit typed model with a validator that reports every
  overlap as structured errors (no reliance on widget option subtraction).
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = REPO_ROOT / "geotestmatch.py"


def _load_app_symbols(*names: str) -> dict:
    """Extract and execute the named top-level functions/classes from geotestmatch.py."""
    import dataclasses

    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    namespace: dict = {
        "dataclass": dataclasses.dataclass,
        "np": np,
        "pd": pd,
        "POPULATION_COL": "Population",
    }
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, str(APP_PATH), "exec"), namespace)
    missing = [n for n in names if n not in namespace]
    assert not missing, f"Symbols not found in {APP_PATH.name}: {missing}"
    return namespace


def _make_agg_df(regions: list[str], pops: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"geo": regions, "Population": pops})


# ---------------------------------------------------------------------------
# Typed constraint model + overlap validation
# ---------------------------------------------------------------------------


class TestMatchConstraints:
    @classmethod
    @pytest.fixture(scope="class")
    def symbols(cls):
        return _load_app_symbols("MatchConstraints", "ConstraintConflict", "validate_constraints")

    def test_typed_model_exists(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        c = MatchConstraints(
            exclude_from_both=("A",),
            force_test_include=("B",),
            test_only_exclude=("C",),
            force_control_include=("D",),
            control_only_exclude=("E",),
        )
        assert c.exclude_from_both == ("A",)
        assert c.force_test_include == ("B",)
        assert c.test_only_exclude == ("C",)
        assert c.force_control_include == ("D",)
        assert c.control_only_exclude == ("E",)

    def test_no_conflicts_for_disjoint_assignments(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(
            exclude_from_both=("A",),
            force_test_include=("B",),
            test_only_exclude=("C",),
            force_control_include=("D",),
            control_only_exclude=("E",),
        )
        assert validate_constraints(c) == ()

    def test_test_include_overlaps_test_exclude(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(force_test_include=("X",), test_only_exclude=("X",))
        conflicts = validate_constraints(c)
        assert len(conflicts) == 1
        assert conflicts[0].region == "X"
        assert set(conflicts[0].fields) == {"force_test_include", "test_only_exclude"}

    def test_test_include_overlaps_control_include(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(force_test_include=("X",), force_control_include=("X",))
        conflicts = validate_constraints(c)
        assert len(conflicts) == 1
        assert conflicts[0].region == "X"
        assert set(conflicts[0].fields) == {"force_control_include", "force_test_include"}

    def test_exclude_from_both_conflicts_with_all_assignments(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(
            exclude_from_both=("X",),
            force_test_include=("X",),
            force_control_include=("X",),
            control_only_exclude=("X",),
        )
        conflicts = validate_constraints(c)
        assert len(conflicts) == 1
        assert conflicts[0].region == "X"
        assert "exclude_from_both" in conflicts[0].fields
        assert len(conflicts[0].fields) == 4

    def test_all_conflicting_regions_reported(self, symbols):
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(
            force_test_include=("X", "Y"),
            force_control_include=("X", "Z"),
            control_only_exclude=("Z",),
        )
        conflicts = validate_constraints(c)
        assert [conf.region for conf in conflicts] == ["X", "Z"]

    def test_one_sided_exclusion_is_not_a_conflict(self, symbols):
        """test_only_exclude + force_control_include is 'control-only' (the
        documented one-sided exclusion semantics), NOT a conflict."""
        MatchConstraints = symbols["MatchConstraints"]
        validate_constraints = symbols["validate_constraints"]
        c = MatchConstraints(test_only_exclude=("X",), force_control_include=("X",))
        assert validate_constraints(c) == ()

        c2 = MatchConstraints(force_test_include=("Y",), control_only_exclude=("Y",))
        assert validate_constraints(c2) == ()


# ---------------------------------------------------------------------------
# Seeded guided search
# ---------------------------------------------------------------------------


class TestGuidedSearchDeterminism:
    @classmethod
    @pytest.fixture(scope="class")
    def symbols(cls):
        return _load_app_symbols("find_guided_test_group", "GuidedSearchConfig")

    def test_seed_defined_in_typed_config(self, symbols):
        GuidedSearchConfig = symbols["GuidedSearchConfig"]
        assert isinstance(GuidedSearchConfig.seed, int)
        cfg = GuidedSearchConfig(seed=123)
        assert cfg.seed == 123

    def test_identical_seed_produces_identical_groups(self, symbols):
        find_guided_test_group = symbols["find_guided_test_group"]
        regions = [f"R{i}" for i in range(30)]
        agg_df = _make_agg_df(regions, [float(i + 1) for i in range(30)])
        kwargs = dict(
            agg_df=agg_df,
            geo_col="geo",
            total_market_pop=float(agg_df["Population"].sum()),
            force_exp_include=["R0"],
            force_exp_exclude=["R1"],
            force_ctrl_include=[],
            force_ctrl_exclude=["R2"],
            target_share=25,
            tolerance_pp=5,
            search_iterations=2000,
        )
        rng_a = np.random.default_rng(42)
        rng_b = np.random.default_rng(42)
        result_a = find_guided_test_group(rng=rng_a, **kwargs)
        result_b = find_guided_test_group(rng=rng_b, **kwargs)
        assert result_a == result_b, "Same seed must produce identical groups"

    def test_forced_and_excluded_regions_respected(self, symbols):
        find_guided_test_group = symbols["find_guided_test_group"]
        regions = [f"R{i}" for i in range(30)]
        agg_df = _make_agg_df(regions, [float(i + 1) for i in range(30)])
        kwargs = dict(
            agg_df=agg_df,
            geo_col="geo",
            total_market_pop=float(agg_df["Population"].sum()),
            force_exp_include=["R0"],
            force_exp_exclude=["R1"],
            force_ctrl_include=[],
            force_ctrl_exclude=["R2"],
            target_share=25,
            tolerance_pp=5,
            search_iterations=2000,
        )
        for seed in (1, 7, 42):
            test_geos, _, met = find_guided_test_group(rng=np.random.default_rng(seed), **kwargs)
            assert "R0" in test_geos, "force-test-include must be in the test group"
            assert "R1" not in test_geos, "test-only-exclude must not be in the test group"
            assert met, "A valid group within tolerance must be found"

    def test_different_seed_can_produce_different_group(self, symbols):
        find_guided_test_group = symbols["find_guided_test_group"]
        regions = [f"R{i}" for i in range(30)]
        agg_df = _make_agg_df(regions, [float(i + 1) for i in range(30)])
        kwargs = dict(
            agg_df=agg_df,
            geo_col="geo",
            total_market_pop=float(agg_df["Population"].sum()),
            force_exp_include=["R0"],
            force_exp_exclude=["R1"],
            force_ctrl_include=[],
            force_ctrl_exclude=["R2"],
            target_share=25,
            tolerance_pp=5,
            search_iterations=2000,
        )
        outcomes = {}
        for seed in (1, 7, 42, 99):
            result = find_guided_test_group(rng=np.random.default_rng(seed), **kwargs)
            outcomes[seed] = (tuple(result[0]), result[1])
        assert len(set(outcomes.values())) > 1, (
            "Different seeds should be able to produce different valid groups; "
            f"got identical outputs for all seeds: {outcomes}"
        )
