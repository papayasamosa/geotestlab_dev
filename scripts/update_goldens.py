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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    return result.stdout.strip()


def _app_baseline_commit() -> str:
    """Return the commit at which the app was last meaningfully changed.
    For now we use HEAD, but this could be pinned to a specific ref."""
    return _current_commit()


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


def main():
    parser = argparse.ArgumentParser(description="Update golden output files.")
    parser.add_argument(
        "--approve",
        action="store_true",
        required=True,
        help="Confirm overwriting existing golden files.",
    )
    args = parser.parse_args()

    if not args.approve:
        print("Use --approve to confirm golden update.")
        sys.exit(1)

    print("Updating golden files...")
    print(f"  App baseline commit: {_app_baseline_commit()}")
    print(f"  Current commit:      {_current_commit()}")
    update_app_tab_labels()
    update_bundled_workbook_structure()
    print("Done.")
    print()
    print("Review the diff:")
    print("  git diff -- tests/golden/")


if __name__ == "__main__":
    main()
