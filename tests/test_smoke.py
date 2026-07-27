"""Startup and baseline safety tests for GeoTestLab.

These tests verify the live Streamlit application starts correctly, dependency
files are portable, and the production app is syntactically valid.
"""

from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Golden schema — all golden files must contain these fields
# ---------------------------------------------------------------------------

REQUIRED_GOLDEN_FIELDS = [
    "schema_version",
    "scenario",
    "fixture_version",
    "app_baseline_commit",
    "golden_created_by_commit",
    "settings",
    "expected",
    "tolerances",
    "known_limitations",
]


# ---------------------------------------------------------------------------
# Syntax / compilation tests
# ---------------------------------------------------------------------------


class TestMainAppSyntax:
    """The main Streamlit app must be syntactically valid Python."""

    @pytest.mark.smoke
    def test_main_app_compiles(self):
        main_path = REPO_ROOT / "geotestmatch.py"
        assert main_path.is_file(), f"Main app not found at {main_path}"
        py_compile.compile(str(main_path), doraise=True)


# ---------------------------------------------------------------------------
# Live Streamlit app tests (using conftest live_app fixture)
# ---------------------------------------------------------------------------


class TestLiveAppStartup:
    """End-to-end tests against the live Streamlit application."""

    @pytest.mark.smoke
    def test_live_app_starts(self, live_app):
        assert not live_app.exception, f"App raised: {live_app.exception}"

    @pytest.mark.smoke
    def test_exact_title(self, live_app):
        assert len(live_app.title) > 0
        assert live_app.title[0].value == "TEST GeoTestLab"

    @pytest.mark.smoke
    def test_exact_tab_labels(self, live_app):
        tab_labels = [t.label for t in live_app.tabs]
        assert tab_labels == [
            "\u2699\ufe0f Region Matching",
            "\U0001f50d Validate Test Design",
            "\U0001f4ca Measure Test Impact",
            "\U0001f9e0 Bayesian TBR",
        ]

    @pytest.mark.smoke
    def test_market_selectbox_label(self, live_app):
        selectboxes = [s for s in live_app.sidebar.selectbox if "Market" in s.label]
        assert len(selectboxes) > 0, "No selectbox with 'Market' label found"

    @pytest.mark.smoke
    def test_sidebar_renders(self, live_app):
        assert live_app.sidebar is not None


# ---------------------------------------------------------------------------
# Bundled data file tests
# ---------------------------------------------------------------------------


class TestBundledData:
    """Verify the bundled demographic workbook exists at the expected path."""

    @pytest.mark.smoke
    def test_bundled_data_file_exists(self):
        data_path = (
            REPO_ROOT
            / "data"
            / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
        )
        assert data_path.exists(), f"Bundled workbook not found: {data_path}"


# ---------------------------------------------------------------------------
# Dependency file portability
# ---------------------------------------------------------------------------


class TestDependencyFilesPortability:
    """Dependency files must be portable and generated on Python 3.11."""

    @pytest.mark.smoke
    def test_no_local_paths_in_requirements(self):
        for fname in ["requirements.txt", "requirements-dev.txt"]:
            path = REPO_ROOT / fname
            assert path.exists(), f"{fname} is missing"
            content = path.read_text(encoding="utf-8")
            for pattern in ["file:///", "C:/", "C:\\", "/Users/", "/home/"]:
                assert pattern not in content, f"{fname} contains {pattern}"

    @pytest.mark.smoke
    def test_lock_files_generated_on_python_311(self):
        """The lock file headers must indicate Python 3.11 generation."""
        for fname in ["requirements.txt", "requirements-dev.txt"]:
            path = REPO_ROOT / fname
            assert path.exists(), f"{fname} is missing"
            lines = path.read_text(encoding="utf-8").split("\n")
            header_line = next((line for line in lines if "Python" in line), "")
            assert "Python 3.11" in header_line, (
                f"{fname} was not generated on Python 3.11: {header_line.strip()}"
            )


# ---------------------------------------------------------------------------
# Golden file schema validation
# ---------------------------------------------------------------------------


class TestGoldenSchema:
    """All golden files must contain the required schema fields."""

    @pytest.mark.smoke
    def test_golden_files_have_valid_schema(self):
        golden_dir = REPO_ROOT / "tests" / "golden"
        json_files = sorted(golden_dir.glob("*.json"))
        assert len(json_files) > 0, "No golden files found"

        for gf in json_files:
            data = json.loads(gf.read_text(encoding="utf-8"))
            for field in REQUIRED_GOLDEN_FIELDS:
                assert field in data, f"{gf.name} missing field: {field}"
            assert isinstance(data["schema_version"], int)
            assert isinstance(data["fixture_version"], int)
            assert isinstance(data["expected"], dict)


# ---------------------------------------------------------------------------
# Python version guard
# ---------------------------------------------------------------------------


class TestPythonVersion:
    """GeoTestLab targets Python 3.11 only."""

    @pytest.mark.smoke
    def test_python_version_is_311(self):
        assert sys.version_info[:2] == (3, 11), (
            f"Python {sys.version_info.major}.{sys.version_info.minor} is not 3.11"
        )
