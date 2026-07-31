#!/usr/bin/env python3
"""Update numerical-characterisation golden files for GeoTestLab (Stage 4).

Usage:
    python scripts/update_numerical_goldens.py --approve

Regenerates tests/golden/numerical_*.json from the live app, driven via
AppTest exactly as tests/test_numerical_characterisation.py does (both
import the same drivers from tests/fixtures/live_scenarios.py, so there is
one source of truth for how each scenario is driven).

This script NEVER runs in CI. The maintainer must review the diff before
committing — a changed golden here means the app's live numerical output
changed, which should be a deliberate, reviewed decision, not a silent
side effect of a refactor.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

sys.path.insert(0, str(REPO_ROOT))


def _git_cmd(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=30,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            f"Git command failed: git {' '.join(args)}\nstderr: {e.stderr.strip()}"
        ) from e
    except FileNotFoundError as e:
        raise SystemExit(f"Git is not available: {e}") from e


def _current_commit() -> str:
    return _git_cmd("rev-parse", "HEAD")


def _app_baseline_commit() -> str:
    return _git_cmd("log", "-1", "--format=%H", "--", "geotestmatch.py")


def _write_safe(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _payload(
    scenario: str, settings: dict, expected: dict, tolerances: dict, known_limitations: list
) -> dict:
    return {
        "schema_version": 1,
        "scenario": scenario,
        "fixture_version": 1,
        "app_baseline_commit": _app_baseline_commit(),
        "golden_created_by_commit": _current_commit(),
        "settings": settings,
        "expected": expected,
        "tolerances": tolerances,
        "known_limitations": known_limitations,
    }


def update_structural_basic():
    from tests.fixtures.live_scenarios import drive_structural_basic

    result = drive_structural_basic()
    payload = _payload(
        scenario="numerical_structural_basic",
        settings={"strategy": "Basic (Fast)", "test_region": "Aberdeen City", "market": "UK"},
        expected=result,
        tolerances={
            "weighted_structural_distance": 1e-6,
            "mean_abs_smd": 1e-6,
            "smd_list": 1e-6,
        },
        known_limitations=[
            "Pinned to the bundled UK demographic workbook; changes to that "
            "workbook's data will change this golden."
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_structural_basic.json", payload)
    print("  Wrote numerical_structural_basic.json")


def update_structural_intermediate():
    from tests.fixtures.live_scenarios import drive_structural_intermediate

    result = drive_structural_intermediate()
    payload = _payload(
        scenario="numerical_structural_intermediate",
        settings={
            "strategy": "Intermediate (Balanced)",
            "test_region": "Aberdeen City",
            "market": "UK",
        },
        expected=result,
        tolerances={
            "weighted_structural_distance": 1e-6,
            "mean_abs_smd": 1e-6,
            "smd_list": 1e-6,
        },
        known_limitations=[
            "Pinned to the bundled UK demographic workbook; changes to that "
            "workbook's data will change this golden."
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_structural_intermediate.json", payload)
    print("  Wrote numerical_structural_intermediate.json")


def update_constraints():
    from tests.fixtures.live_scenarios import drive_constraints

    result = drive_constraints()
    payload = _payload(
        scenario="numerical_constraints",
        settings={
            "setup_mode": "Set Rules & Auto-Build Groups",
            "market": "UK",
            "guided_seed": 42,
        },
        expected=result,
        tolerances={},
        known_limitations=[
            "force_ctrl_include guarantees pool ELIGIBILITY for the guided "
            "search / matching strategy, not guaranteed presence in the final "
            "selected control group — the matching strategy can still leave it "
            "unselected if it doesn't improve Weighted Structural Distance. "
            "The golden records forced_control_region_in_candidate_pool (True, "
            "by definition) separately from "
            "forced_control_region_in_control_group (strategy-dependent).",
            "The guided search is seeded (GuidedSearchConfig.seed = 42, an "
            "injected numpy Generator). Group sizes and the achieved share are "
            "now reproducible and compared exactly; a different seed can "
            "produce a different (still valid) group.",
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_constraints.json", payload)
    print("  Wrote numerical_constraints.json")


def update_kpi_pattern():
    from tests.fixtures.live_scenarios import drive_kpi_pattern

    with tempfile.TemporaryDirectory() as tmp:
        result = drive_kpi_pattern(Path(tmp))
    payload = _payload(
        scenario="numerical_kpi_pattern",
        settings={
            "fixture": "write_aggregated_kpi_xlsx",
            "regions": ["RegionA", "RegionB", "RegionC", "RegionD", "RegionE"],
            "n_weeks": 20,
            "seed": 55,
        },
        expected=result,
        tolerances={"weighted_structural_distance": 1e-6, "mean_abs_smd": 1e-6},
        known_limitations=[],
    )
    _write_safe(GOLDEN_DIR / "numerical_kpi_pattern.json", payload)
    print("  Wrote numerical_kpi_pattern.json")


def update_weekly_validation():
    from tests.fixtures.live_scenarios import drive_weekly_validation

    with tempfile.TemporaryDirectory() as tmp:
        result = drive_weekly_validation(Path(tmp))
    payload = _payload(
        scenario="numerical_weekly_validation",
        settings={
            "fixture": "write_simple_kpi_xlsx",
            "test_region": "Aberdeen City",
            "control_regions": ["Aberdeenshire", "Angus"],
            "n_weeks": 60,
            "seed": 123,
            "mode": "Design",
        },
        expected=result,
        tolerances={
            "smape": 1e-4,
            "rmse": 1e-4,
            "rolling_smape_mean": 1e-4,
            "rolling_rmse_mean": 1e-4,
            "rolling_bias_pct_mean": 1e-4,
            "dw_stat": 1e-6,
        },
        known_limitations=[
            "Rolling-origin folds and the underlying ElasticNetCV fit depend on "
            "scikit-learn's numerical implementation; pinned scikit-learn "
            "version keeps this reproducible.",
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_weekly_validation.json", payload)
    print("  Wrote numerical_weekly_validation.json")


def update_completed_test_evaluation():
    from tests.fixtures.live_scenarios import drive_completed_test_evaluation

    with tempfile.TemporaryDirectory() as tmp:
        result = drive_completed_test_evaluation(Path(tmp))
    payload = _payload(
        scenario="numerical_completed_test_evaluation",
        settings={
            "fixture": "write_simple_kpi_xlsx",
            "test_region": "Aberdeen City",
            "control_regions": ["Aberdeenshire", "Angus"],
            "n_weeks": 60,
            "seed": 123,
            "mode": "Evaluate",
        },
        expected=result,
        tolerances={
            "smape": 1e-4,
            "rmse": 1e-4,
            "rolling_smape_mean": 1e-4,
            "rolling_rmse_mean": 1e-4,
            "dw_stat": 1e-6,
            "uplift": 1e-4,
            "uplift_pct": 1e-4,
            "actual_total": 1e-4,
            "counterfactual_total": 1e-4,
            "median_placebo_uplift": 1e-4,
            "placebo_range_lower": 1e-4,
            "placebo_range_upper": 1e-4,
            "placebo_percentile_rank": 1e-6,
            "placebo_p_value_one_sided": 1e-6,
            "placebo_p_value_two_sided": 1e-6,
            "placebo_z_score": 1e-4,
        },
        known_limitations=[
            "Placebo statistics are capped at 40 evenly-spaced windows "
            "(_run_placebo_windows(max_windows=40)); percentile-rank/p-value "
            "resolution is limited to roughly 1/40.",
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_completed_test_evaluation.json", payload)
    print("  Wrote numerical_completed_test_evaluation.json")


def update_daily_evaluation():
    from tests.fixtures.live_scenarios import drive_daily_evaluation

    with tempfile.TemporaryDirectory() as tmp:
        result = drive_daily_evaluation(Path(tmp))
    payload = _payload(
        scenario="numerical_daily_evaluation",
        settings={
            "fixture": "write_daily_kpi_xlsx",
            "test_region": "Aberdeen City",
            "control_regions": ["Aberdeenshire", "Angus"],
            "n_days": 150,
            "seed": 321,
            "mode": "Evaluate",
            "frequency": "daily",
            "include_lagged_controls": True,
        },
        expected=result,
        tolerances={
            "smape": 1e-4,
            "rmse": 1e-4,
            "rolling_smape_mean": 1e-4,
            "rolling_rmse_mean": 1e-4,
            "dw_stat": 1e-6,
            "uplift": 1e-4,
            "uplift_pct": 1e-4,
            "actual_total": 1e-4,
            "counterfactual_total": 1e-4,
        },
        known_limitations=[
            "Daily lag length is fixed at 7 periods (get_frequency_config); "
            "changing that mapping would change rows-dropped-to-lag here.",
        ],
    )
    _write_safe(GOLDEN_DIR / "numerical_daily_evaluation.json", payload)
    print("  Wrote numerical_daily_evaluation.json")


SCENARIOS = [
    ("structural_basic", update_structural_basic),
    ("structural_intermediate", update_structural_intermediate),
    ("constraints", update_constraints),
    ("kpi_pattern", update_kpi_pattern),
    ("weekly_validation", update_weekly_validation),
    ("completed_test_evaluation", update_completed_test_evaluation),
    ("daily_evaluation", update_daily_evaluation),
]


def main():
    parser = argparse.ArgumentParser(description="Update numerical characterisation golden files.")
    parser.add_argument(
        "--approve",
        action="store_true",
        required=True,
        help="Confirm overwriting existing golden files.",
    )
    parser.add_argument(
        "--only",
        choices=[name for name, _ in SCENARIOS],
        help="Regenerate only one scenario's golden (for iterating).",
    )
    args = parser.parse_args()

    if os.environ.get("CI"):
        raise SystemExit("Golden files must not be updated in CI.")

    if not args.approve:
        print("Use --approve to confirm golden update.")
        sys.exit(1)

    if not GOLDEN_DIR.exists():
        raise SystemExit(f"Golden directory not found: {GOLDEN_DIR}")

    status = _git_cmd("status", "--porcelain", "--untracked-files=all")
    # Golden JSON files themselves are expected to be dirty when regenerating;
    # only fail on unrelated uncommitted changes elsewhere in the tree.
    dirty_non_golden = [
        line
        for line in status.strip().splitlines()
        if "tests/golden/" not in line.replace("\\", "/")
    ]
    if dirty_non_golden:
        print("ERROR: Working tree has uncommitted non-golden changes.", file=sys.stderr)
        print("Commit or stash your changes before updating golden files.", file=sys.stderr)
        for line in dirty_non_golden:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)

    print("Updating numerical characterisation golden files...")
    print(f"  App baseline commit (last change to geotestmatch.py): {_app_baseline_commit()}")
    print(f"  Current commit:      {_current_commit()}")

    targets = SCENARIOS if not args.only else [(n, f) for n, f in SCENARIOS if n == args.only]
    for name, fn in targets:
        print(f"  Running scenario: {name}")
        fn()

    print("Done.")
    print()
    print("Review the diff:")
    print("  git diff -- tests/golden/numerical_*.json")


if __name__ == "__main__":
    main()
