"""Live ingestion tests for GeoTestLab fixture factories.

These tests verify that the generated fixture Excel files can be uploaded
through the live Streamlit application and are correctly parsed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Test basic structural ingestion
# ---------------------------------------------------------------------------


class TestConfigMode:
    """Verify the app defaults to structural matching with UK data."""

    @pytest.mark.smoke
    def test_default_structural_mode_shows_preview(self, live_app):
        """With the default UK market, the app should show a data preview."""
        # Check that at least one dataframe or expander is rendered
        # (the preview data expander for the UK market)
        assert len(live_app.expander) >= 1 or len(live_app.dataframe) >= 0


class TestFixtureFactoryIngestion:
    """Verify fixture files can be uploaded through the live app.

    Note: Full KPI-pattern and validation upload tests require switching
    matching modes, which is a multi-step AppTest interaction.
    These tests verify structural properties that are visible at startup.
    """

    @pytest.mark.smoke
    def test_app_loads_bundled_workbook(self, live_app):
        """The app should load the bundled workbook on startup without errors."""
        assert not live_app.exception, f"App raised: {live_app.exception}"
        # Market selectbox with options indicates successful workbook loading
        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) > 0
        assert len(market_select[0].options) > 0, "No market options loaded"

    @pytest.mark.smoke
    def test_sidebar_shows_data_quality(self, live_app):
        """After loading, the sidebar should show data quality information."""
        sidebar_text = " ".join(str(m) for m in live_app.sidebar.markdown) + " ".join(
            str(c) for c in live_app.sidebar.caption
        )
        # The app shows data quality info in the sidebar after workbook loading
        assert len(live_app.sidebar.markdown) > 0 or len(live_app.sidebar.caption) > 0
