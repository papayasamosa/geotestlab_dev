"""Startup and baseline safety tests for GeoTestLab.

These tests verify the live Streamlit application starts correctly, dependency
files are portable, and the production app is syntactically valid.
"""

import py_compile
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Syntax / compilation tests
# ---------------------------------------------------------------------------


class TestMainAppSyntax:
    """The main Streamlit app must be syntactically valid Python.

    We do NOT import the module because ``st.set_page_config()`` at the top
    level requires a running Streamlit context.  ``py_compile`` catches syntax
    and indentation errors without executing the module body.
    """

    @pytest.mark.smoke
    def test_main_app_compiles(self):
        main_path = REPO_ROOT / "geotestmatch.py"
        assert main_path.is_file(), f"Main app not found at {main_path}"
        py_compile.compile(str(main_path), doraise=True)


# ---------------------------------------------------------------------------
# Live Streamlit app tests
# ---------------------------------------------------------------------------


class TestLiveAppStartup:
    """End-to-end tests against the live Streamlit application.

    These tests use ``streamlit.testing.v1.AppTest`` to run the app in
    headless mode and verify its structure.  They do NOT start a server.
    """

    @pytest.mark.smoke
    def test_live_app_starts(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert not app.exception, f"App raised: {app.exception}"

    @pytest.mark.smoke
    def test_app_has_expected_title(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert len(app.title) > 0
        assert "GeoTestLab" in app.title[0].value

    @pytest.mark.smoke
    def test_app_has_four_workflow_tabs(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        assert len(app.tabs) >= 4

    @pytest.mark.smoke
    def test_sidebar_renders(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        # The sidebar should render without throwing
        assert app.sidebar is not None

    @pytest.mark.smoke
    def test_market_selectbox_exists(self):
        """The app should have a market/sheet selectbox in the sidebar."""
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        # Look for a selectbox labelled "Market" or "Sheet"
        selectboxes = [s for s in app.sidebar.selectbox if "market" in s.label.lower()]
        assert len(selectboxes) > 0, "No market selectbox found in sidebar"

    @pytest.mark.smoke
    def test_app_has_no_uncaught_exceptions(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=120)
        # Check for script errors — the app may produce warnings but no
        # unhandled exceptions should terminate execution.
        assert not app.exception, f"App raised: {app.exception}"


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
    """Dependency files must not contain absolute local paths."""

    @pytest.mark.smoke
    def test_no_local_paths_in_requirements(self):
        for fname in ["requirements.txt", "requirements-dev.txt"]:
            path = REPO_ROOT / fname
            if not path.exists():
                pytest.skip(f"{fname} not found — will be generated in a later step")
            content = path.read_text(encoding="utf-8")
            assert "file:///" not in content, f"{fname} contains a local absolute path (file:///)"


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
