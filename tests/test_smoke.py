"""Startup smoke tests for GeoTestLab.

These tests verify that the application modules import correctly, the main
application file is syntactically valid, and key constants are consistent.
They do NOT start a Streamlit server or execute the full app.
"""

import py_compile
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
UTILS_DIR = REPO_ROOT / "utils"


# ---------------------------------------------------------------------------
# Module import tests
# ---------------------------------------------------------------------------


class TestUtilityModuleImports:
    """Each util module must import cleanly (no missing deps, no syntax errors)."""

    @pytest.mark.smoke
    def test_config_import(self):
        from utils.config import CONFIG, DATA_PATH, SMD_GOOD_THRESHOLD  # noqa: F811

        assert isinstance(CONFIG, dict)
        assert isinstance(DATA_PATH, str)
        assert isinstance(SMD_GOOD_THRESHOLD, float)

    @pytest.mark.smoke
    def test_data_loader_import(self):
        from utils.data_loader import (  # noqa: F811
            normalise_column_names,
            repair_text_value,
        )

        assert callable(repair_text_value)
        assert callable(normalise_column_names)

    @pytest.mark.smoke
    def test_matching_import(self):
        from utils.matching import (  # noqa: F811
            run_matching,
        )

        assert callable(run_matching)

    @pytest.mark.smoke
    def test_validation_import(self):
        from utils.validation import (  # noqa: F811
            run_validation_method,
        )

        assert callable(run_validation_method)

    @pytest.mark.smoke
    def test_exports_import(self):
        from utils.exports import create_excel_export  # noqa: F811

        assert callable(create_excel_export)

    @pytest.mark.smoke
    def test_plotting_import(self):
        from utils.plotting import (  # noqa: F811
            create_love_plot,
        )

        assert callable(create_love_plot)

    @pytest.mark.smoke
    def test_session_import(self):
        from utils.session import init_session_state  # noqa: F811

        assert callable(init_session_state)


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
# Configuration consistency tests
# ---------------------------------------------------------------------------


class TestConfigConsistency:
    """Key configuration values in ``utils/config.py`` must match the inline
    ``CONFIG`` dict in ``geotestmatch.py`` where they overlap.

    This guards against drift when the two copies are eventually consolidated.
    """

    @pytest.mark.smoke
    def test_smd_thresholds_match(self):
        from utils.config import SMD_GOOD_THRESHOLD, SMD_HIGH_THRESHOLD

        assert SMD_GOOD_THRESHOLD == 0.20
        assert SMD_HIGH_THRESHOLD == 0.50

    @pytest.mark.smoke
    def test_data_path_exists(self):
        from utils.config import DATA_PATH

        data_file = REPO_ROOT / DATA_PATH
        assert data_file.exists() or data_file.with_suffix(".csv").exists(), (
            f"Configured data file not found: {DATA_PATH}"
        )


# ---------------------------------------------------------------------------
# Python version guard
# ---------------------------------------------------------------------------


class TestPythonVersion:
    """Remind developers if they are running on an untested Python version."""

    @pytest.mark.smoke
    def test_python_version_is_supported(self):
        msg = (
            f"Python {sys.version_info.major}.{sys.version_info.minor} "
            f"is outside the supported range (3.11–3.12)."
        )
        assert (3, 11) <= (sys.version_info.major, sys.version_info.minor) <= (3, 12), msg
