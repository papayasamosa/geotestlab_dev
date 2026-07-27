"""Live app characterisation tests for GeoTestLab.

These tests exercise the live Streamlit application via AppTest and verify
its structure against read-only golden files.  They do NOT create or update
golden files — that is done by ``scripts/update_goldens.py --approve``.

Golden output files in ``tests/golden/`` identify the baseline commit and
contain structured expected values.
"""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _load_golden(name: str) -> dict:
    """Load a golden file.  Tests fail if the file is missing."""
    path = GOLDEN_DIR / f"{name}.json"
    assert path.exists(), (
        f"Golden file {path.name} not found. "
        f"Run 'python scripts/update_goldens.py --approve' to create it."
    )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# App structure characterisation (read-only golden comparison)
# ---------------------------------------------------------------------------


class TestAppStructure:
    """Characterise the structural properties of the live app."""

    @pytest.mark.smoke
    def test_live_app_starts_without_exception(self, live_app):
        assert not live_app.exception, f"App raised: {live_app.exception}"

    @pytest.mark.smoke
    def test_tab_labels_match_golden(self, live_app):
        golden = _load_golden("app_tab_labels")
        tab_labels = [t.label for t in live_app.tabs]
        expected = golden["expected"]["tab_labels"]
        assert tab_labels == expected, f"Tab labels differ: {tab_labels} != {expected}"

    @pytest.mark.smoke
    def test_bundled_workbook_matches_golden(self):
        """The workbook sheet names must match the golden file exactly."""
        golden = _load_golden("bundled_workbook_structure")
        data_path = (
            REPO_ROOT
            / "data"
            / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
        )
        wb = openpyxl.load_workbook(data_path, read_only=True)
        sheet_names = wb.sheetnames
        wb.close()

        expected_sheets = golden["expected"]["sheet_names"]
        assert list(sheet_names) == expected_sheets, (
            f"Sheet names differ: {list(sheet_names)} != {expected_sheets}"
        )
