#!/usr/bin/env python3
"""Update golden output files for GeoTestLab characterisation tests.

Usage:
    python scripts/update_goldens.py --approve

This script regenerates all golden files from the current live app state.
It NEVER runs in CI.  The maintainer must review the diff before committing.

Requirements:
    --approve   Confirm that golden files should be overwritten.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _git_cmd(*args: str) -> str:
    """Run a git command and return trimmed stdout.  Raises on failure."""
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
    """Return the full SHA of the last commit that changed the live app file."""
    return _git_cmd("log", "-1", "--format=%H", "--", "geotestmatch.py")


def _write_safe(path: Path, payload: dict) -> None:
    """Write payload to path via a temporary file to avoid partial writes."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_app_tab_labels():
    """Capture the live app's tab labels."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
    app.run(timeout=180)

    tab_labels = [t.label for t in app.tabs]
    payload = {
        "schema_version": 1,
        "scenario": "app_tab_labels",
        "fixture_version": 1,
        "app_baseline_commit": _app_baseline_commit(),
        "golden_created_by_commit": _current_commit(),
        "settings": {},
        "expected": {"tab_labels": tab_labels, "n_tabs": len(tab_labels)},
        "tolerances": {},
        "known_limitations": [],
    }
    path = GOLDEN_DIR / "app_tab_labels.json"
    print(f"  Writing {path.name}")
    _write_safe(path, payload)


def update_bundled_workbook_structure():
    """Capture the bundled workbook's sheet metadata."""
    import openpyxl

    data_path = (
        REPO_ROOT
        / "data"
        / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
    )
    wb = openpyxl.load_workbook(data_path, read_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    payload = {
        "schema_version": 1,
        "scenario": "bundled_workbook_structure",
        "fixture_version": 1,
        "app_baseline_commit": _app_baseline_commit(),
        "golden_created_by_commit": _current_commit(),
        "settings": {},
        "expected": {
            "n_sheets": len(sheet_names),
            "sheet_names": list(sheet_names),
        },
        "tolerances": {},
        "known_limitations": ["Sheet count may change when markets are added or removed."],
    }
    path = GOLDEN_DIR / "bundled_workbook_structure.json"
    print(f"  Writing {path.name}")
    _write_safe(path, payload)


def update_available_markets():
    """Capture the available market options from the live app."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
    app.run(timeout=180)

    market_select = [s for s in app.sidebar.selectbox if s.label == "Market"]
    assert len(market_select) == 1, "Expected exactly one Market selectbox"
    markets = list(market_select[0].options)

    payload = {
        "schema_version": 1,
        "scenario": "available_markets",
        "fixture_version": 1,
        "app_baseline_commit": _app_baseline_commit(),
        "golden_created_by_commit": _current_commit(),
        "settings": {},
        "expected": {
            "markets": markets,
            "default_market": str(market_select[0].value),
        },
        "tolerances": {},
        "known_limitations": ["Market list depends on bundled workbook sheets."],
    }
    path = GOLDEN_DIR / "available_markets.json"
    print(f"  Writing {path.name}")
    _write_safe(path, payload)


def main():
    parser = argparse.ArgumentParser(description="Update golden output files.")
    parser.add_argument(
        "--approve",
        action="store_true",
        required=True,
        help="Confirm overwriting existing golden files.",
    )
    args = parser.parse_args()

    # Never run in CI
    if os.environ.get("CI"):
        raise SystemExit("Golden files must not be updated in CI.")

    if not args.approve:
        print("Use --approve to confirm golden update.")
        sys.exit(1)

    # Verify the golden directory and working tree are accessible
    if not GOLDEN_DIR.exists():
        raise SystemExit(f"Golden directory not found: {GOLDEN_DIR}")
    try:
        _git_cmd("rev-parse", "--git-dir")
    except SystemExit:
        print("WARNING: Working tree metadata unavailable; commit fields may be incorrect.")

    # Require a clean working tree — golden files must be generated from
    # a committed state so that golden_created_by_commit is truthful.
    status = _git_cmd("status", "--porcelain", "--untracked-files=all")
    if status.strip():
        print("ERROR: Working tree is not clean.", file=sys.stderr)
        print("Commit or stash your changes before updating golden files.", file=sys.stderr)
        print("Dirty files:")
        for line in status.strip().splitlines():
            print(f"  {line}")
        sys.exit(1)

    print("Updating golden files...")
    print(f"  App baseline commit (last change to geotestmatch.py): {_app_baseline_commit()}")
    print(f"  Current commit:      {_current_commit()}")
    print("  Files to write:")
    for name in ["app_tab_labels", "bundled_workbook_structure", "available_markets"]:
        print(f"    {GOLDEN_DIR / name}.json")
    update_app_tab_labels()
    update_bundled_workbook_structure()
    update_available_markets()
    print("Done.")
    print()
    print("Review the diff:")
    print("  git diff -- tests/golden/")


if __name__ == "__main__":
    main()
