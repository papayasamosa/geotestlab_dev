"""Shared fixtures for GeoTestLab tests."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def live_app():
    """Start the live Streamlit app once per module.

    Returns an ``AppTest`` instance with the app already executed.
    Use ``app.run()`` again only if widget interaction requires re-run.
    """
    app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
    app.run(timeout=180)
    return app
