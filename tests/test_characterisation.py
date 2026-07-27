"""Live app characterisation tests for GeoTestLab.

These tests exercise the live Streamlit application via AppTest and capture
key structural properties as golden values.  They do NOT modify application
code or require internal module access.

Golden output files in ``tests/golden/`` identify the baseline commit.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _baseline_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    return result.stdout.strip()


def _golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def _save_golden(name: str, data: dict):
    path = _golden_path(name)
    payload = {
        "baseline_commit": _baseline_commit(),
        "fixture_version": "1.0",
        "scenario": name,
        "data": data,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))


def _load_golden(name: str) -> dict | None:
    path = _golden_path(name)
    if path.exists():
        return json.loads(path.read_text())
    return None


# ---------------------------------------------------------------------------
# App structure characterisation
# ---------------------------------------------------------------------------


class TestAppStructure:
    """Characterise the structural properties of the live app."""

    @pytest.mark.smoke
    def test_live_app_starts_without_exception(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert not app.exception, f"App raised: {app.exception}"

    @pytest.mark.smoke
    def test_page_title_contains_geotestlab(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert len(app.title) > 0
        assert "GeoTestLab" in app.title[0].value

    @pytest.mark.smoke
    def test_four_workflow_tabs_exist(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        tab_labels = [t.label for t in app.tabs]
        assert len(tab_labels) == 4

        expected_keywords = ["Region Matching", "Validate", "Measure", "Bayesian"]
        for keyword in expected_keywords:
            found = any(keyword.lower() in label.lower() for label in tab_labels)
            assert found, f"Expected tab with '{keyword}' not found in {tab_labels}"

        # Save golden if first run
        golden_data = {"tab_labels": tab_labels, "n_tabs": len(tab_labels)}
        existing = _load_golden("app_tab_labels")
        if existing is None:
            _save_golden("app_tab_labels", golden_data)
        else:
            assert golden_data["n_tabs"] == existing["data"]["n_tabs"]
            assert golden_data["tab_labels"] == existing["data"]["tab_labels"]

    @pytest.mark.smoke
    def test_sidebar_renders_with_content(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert app.sidebar is not None

    @pytest.mark.smoke
    def test_market_selectbox_exists(self):
        """The app should have a market/sheet selectbox in the sidebar."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        selectboxes = [s for s in app.sidebar.selectbox if "market" in s.label.lower()]
        assert len(selectboxes) > 0, "No market selectbox found in sidebar"


# ---------------------------------------------------------------------------
# Bundled data characterisation
# ---------------------------------------------------------------------------


class TestBundledDataCharacterisation:
    """Characterise the bundled demographic workbook."""

    @pytest.mark.smoke
    def test_bundled_workbook_exists(self):
        data_path = (
            REPO_ROOT
            / "data"
            / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
        )
        assert data_path.exists(), f"Bundled workbook not found at {data_path}"
        assert data_path.stat().st_size > 0

    @pytest.mark.smoke
    def test_workbook_has_expected_sheets(self):
        import openpyxl

        data_path = (
            REPO_ROOT
            / "data"
            / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
        )
        wb = openpyxl.load_workbook(data_path, read_only=True)
        sheet_names = wb.sheetnames
        wb.close()

        assert len(sheet_names) > 0, "Workbook has no sheets"

        golden_data = {
            "n_sheets": len(sheet_names),
            "first_10_sheets": sheet_names[:10],
        }
        existing = _load_golden("bundled_workbook_structure")
        if existing is None:
            _save_golden("bundled_workbook_structure", golden_data)
        else:
            assert golden_data["n_sheets"] == existing["data"]["n_sheets"]


# ---------------------------------------------------------------------------
# Synthetic fixture verification
# ---------------------------------------------------------------------------


class TestSyntheticFixtures:
    """Verify the synthetic data fixtures produce valid output."""

    @pytest.mark.smoke
    def test_synthetic_demographic_data_shape(self):
        from tests.fixtures.synthetic_data import synthetic_demographic_data

        df = synthetic_demographic_data(n_regions=10, seed=42)
        assert len(df) == 10
        assert "Region" in df.columns
        assert "Population" in df.columns
        assert "Median Income" in df.columns
        assert df.isnull().sum().sum() == 0

    @pytest.mark.smoke
    def test_synthetic_kpi_data_shape(self):
        from tests.fixtures.synthetic_data import synthetic_kpi_data

        df = synthetic_kpi_data(regions=["A", "B"], n_weeks=10, seed=42)
        assert len(df) == 2 * 10
        assert "date" in df.columns
        assert "kpi" in df.columns
        assert df["kpi"].notna().all()

    @pytest.mark.smoke
    def test_synthetic_kpi_data_deterministic(self):
        from tests.fixtures.synthetic_data import synthetic_kpi_data

        df1 = synthetic_kpi_data(regions=["A"], n_weeks=5, seed=42)
        df2 = synthetic_kpi_data(regions=["A"], n_weeks=5, seed=42)
        assert df1["kpi"].tolist() == df2["kpi"].tolist()
