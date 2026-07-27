"""Live numerical characterisation tests for GeoTestLab (Stage 4).

These tests drive the live app via the same AppTest scenarios used to
generate the golden files (tests/fixtures/live_scenarios.py) and compare
the result against the frozen golden JSON in tests/golden/. They do NOT
create or update golden files — that is done by
`scripts/update_numerical_goldens.py --approve`.

Identities and counts (region names, layout labels, row/fold counts) are
compared exactly. Floats derived from ElasticNetCV/LASSO fits, rolling-
origin folds, and placebo loops are compared with the explicit per-metric
tolerance recorded in each golden file's `tolerances` dict — there is no
single blanket tolerance.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from tests.fixtures.live_scenarios import (
    drive_completed_test_evaluation,
    drive_constraints,
    drive_daily_evaluation,
    drive_kpi_pattern,
    drive_structural_basic,
    drive_structural_intermediate,
    drive_weekly_validation,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _load_golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.json"
    assert path.exists(), (
        f"Golden file {path.name} not found. "
        f"Run 'python scripts/update_numerical_goldens.py --approve' to create it."
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_value_matches(path: str, actual, expected, tol) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        for key, sub_expected in expected.items():
            sub_tol = tol.get(key) if isinstance(tol, dict) else tol
            _assert_value_matches(f"{path}.{key}", actual.get(key), sub_expected, sub_tol)
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual)}"
        assert len(actual) == len(expected), (
            f"{path}: length differs — actual {len(actual)} != expected {len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_value_matches(f"{path}[{i}]", a, e, tol)
        return

    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if isinstance(expected, float) and math.isnan(expected):
            assert actual is None or (isinstance(actual, float) and math.isnan(actual)), (
                f"{path}: expected NaN, got {actual!r}"
            )
            return
        if tol is not None:
            assert actual is not None, f"{path}: expected {expected!r}, got None"
            assert math.isclose(actual, expected, abs_tol=tol, rel_tol=0), (
                f"{path}: {actual!r} not within tolerance {tol} of expected {expected!r}"
            )
        else:
            assert actual == expected, f"{path}: {actual!r} != expected {expected!r} (exact)"
        return

    assert actual == expected, f"{path}: {actual!r} != expected {expected!r} (exact)"


def _assert_matches_golden(actual: dict, golden: dict) -> None:
    _assert_value_matches("expected", actual, golden["expected"], golden.get("tolerances", {}))


# ---------------------------------------------------------------------------
# 1-2. Structural Basic / Intermediate
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_structural_basic_matches_golden():
    golden = _load_golden("numerical_structural_basic")
    actual = drive_structural_basic()
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)


@pytest.mark.slow
def test_structural_intermediate_matches_golden():
    golden = _load_golden("numerical_structural_intermediate")
    actual = drive_structural_intermediate()
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)


# ---------------------------------------------------------------------------
# 3. Constraints
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestConstraints:
    @pytest.fixture(scope="class")
    def result(self):
        return drive_constraints()

    def test_forced_test_region_is_included(self, result):
        assert result["constraints"]["forced_test_region_in_test_group"] is True

    def test_excluded_test_region_is_absent(self, result):
        assert result["constraints"]["excluded_test_region_in_test_group"] is False

    def test_excluded_control_region_is_absent_from_controls(self, result):
        assert result["constraints"]["excluded_control_region_in_control_group"] is False

    def test_conflict_is_silently_resolved_not_hard_stopped(self, result):
        """Documents the real, current behaviour: the app's own conflict
        check (st.error + st.stop) is unreachable via sequential live-widget
        interaction, because Streamlit drops the now-stale ctrl_include
        selection once exp_include claims the same region. See the golden's
        known_limitations for the full explanation."""
        conflict = result["conflict"]
        assert conflict["exception"] is False
        assert conflict["errors"] == []
        assert conflict["ctrl_include_value_after_conflict_attempt"] == []
        assert len(conflict["exp_include_value_after_conflict_attempt"]) == 1

    def test_matches_golden(self, result):
        golden = _load_golden("numerical_constraints")
        _assert_matches_golden(result, golden)


# ---------------------------------------------------------------------------
# 4. KPI pattern
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_kpi_pattern_matches_golden(tmp_path):
    golden = _load_golden("numerical_kpi_pattern")
    actual = drive_kpi_pattern(tmp_path)
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)


# ---------------------------------------------------------------------------
# 5. Weekly validation
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_weekly_validation_matches_golden(tmp_path):
    golden = _load_golden("numerical_weekly_validation")
    actual = drive_weekly_validation(tmp_path)
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)


# ---------------------------------------------------------------------------
# 6. Completed-test evaluation
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_completed_test_evaluation_matches_golden(tmp_path):
    golden = _load_golden("numerical_completed_test_evaluation")
    actual = drive_completed_test_evaluation(tmp_path)
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)


# ---------------------------------------------------------------------------
# 7. Daily evaluation
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_daily_evaluation_matches_golden(tmp_path):
    golden = _load_golden("numerical_daily_evaluation")
    actual = drive_daily_evaluation(tmp_path)
    assert not actual["exception"]
    _assert_matches_golden(actual, golden)
