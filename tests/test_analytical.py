"""Analytical characterisation tests for GeoTestLab.

These tests exercise the live Streamlit application via AppTest and capture
key structural and configuration properties as golden outputs.  They do NOT
create or update golden files — that is done by ``scripts/update_goldens.py
--approve``.

Golden output files in ``tests/golden/`` identify the baseline commit.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"


def _load_golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.json"
    assert path.exists(), (
        f"Golden file {path.name} not found. "
        f"Run 'python scripts/update_goldens.py --approve' to create it."
    )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# App configuration characterisation
# ---------------------------------------------------------------------------


class TestAppConfiguration:
    """Characterise the app's default settings and available options."""

    @pytest.mark.smoke
    def test_default_market_is_uk(self, live_app):
        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) == 1
        assert market_select[0].value == "UK"

    @pytest.mark.smoke
    def test_default_matching_method(self, live_app):
        method_radio = [r for r in live_app.sidebar.radio if r.label == "Matching method"]
        assert len(method_radio) == 1
        assert method_radio[0].value == "Structural"

    @pytest.mark.smoke
    def test_default_strategy(self, live_app):
        strategy_radio = [r for r in live_app.sidebar.radio if r.label == "Strategy"]
        assert len(strategy_radio) == 1
        assert strategy_radio[0].value == "Basic (Fast)"

    @pytest.mark.smoke
    def test_strategy_options(self, live_app):
        strategy_radio = [r for r in live_app.sidebar.radio if r.label == "Strategy"]
        assert len(strategy_radio) == 1
        options = strategy_radio[0].options
        assert "Basic (Fast)" in options
        assert "Intermediate (Balanced)" in options
        assert "Advanced (Thorough)" in options

    @pytest.mark.smoke
    def test_default_geography_level(self, live_app):
        geo_select = [s for s in live_app.sidebar.selectbox if s.label == "Geography Level"]
        assert len(geo_select) == 1
        assert geo_select[0].value is not None
        assert geo_select[0].value != ""


# ---------------------------------------------------------------------------
# Market list characterisation
# ---------------------------------------------------------------------------


class TestMarketList:
    """Characterise the available markets from the bundled workbook."""

    @pytest.mark.smoke
    def test_market_list_matches_golden(self, live_app):
        golden = _load_golden("available_markets")
        expected_markets = golden["expected"]["markets"]

        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) == 1
        actual_markets = list(market_select[0].options)

        assert actual_markets == expected_markets, (
            f"Market list differs: {actual_markets} != {expected_markets}"
        )


# ---------------------------------------------------------------------------
# Feature weight controls
# ---------------------------------------------------------------------------


class TestFeatureWeights:
    """Characterise the feature weight sliders."""

    @pytest.mark.smoke
    def test_feature_sliders_present(self, live_app):
        feature_sliders = [
            s
            for s in live_app.sidebar.slider
            if s.label not in ("Population", "Population Density")
        ]
        assert len(feature_sliders) >= 5

    @pytest.mark.smoke
    def test_default_weights_are_one(self, live_app):
        feature_sliders = [
            s
            for s in live_app.sidebar.slider
            if s.label not in ("Population", "Population Density")
        ]
        for s in feature_sliders[:5]:
            assert s.value == 1.0, f"Slider '{s.label}' default is {s.value}, expected 1.0"


# ---------------------------------------------------------------------------
# Fixture factory tests
# ---------------------------------------------------------------------------


class TestFixtureFactories:
    """Verify the fixture factory functions produce valid Excel files."""

    @pytest.mark.smoke
    def test_simple_kpi_xlsx_creation(self):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        with tempfile.TemporaryDirectory() as tmp:
            path = write_simple_kpi_xlsx(
                Path(tmp) / "simple_kpi.xlsx",
                regions=["Region_A", "Region_B"],
                n_weeks=10,
                seed=42,
            )
            assert path.exists()
            assert path.stat().st_size > 0

            import pandas as pd

            df = pd.read_excel(path, engine="openpyxl")
            assert "Region" in df.columns
            assert "Metric" in df.columns

    @pytest.mark.smoke
    def test_aggregated_kpi_xlsx_creation(self):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import write_aggregated_kpi_xlsx

        with tempfile.TemporaryDirectory() as tmp:
            path = write_aggregated_kpi_xlsx(
                Path(tmp) / "agg_kpi.xlsx",
                regions=["Region_A", "Region_B"],
                n_weeks=10,
                seed=42,
            )
            assert path.exists()
            import pandas as pd

            df = pd.read_excel(path, engine="openpyxl")
            assert "Store ID" in df.columns
            assert "TV Region" in df.columns

    @pytest.mark.smoke
    def test_kpi_pattern_xlsx_creation(self):
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        with tempfile.TemporaryDirectory() as tmp:
            path = write_kpi_pattern_xlsx(
                Path(tmp) / "kpi_pattern.xlsx",
                regions=["Region_A", "Region_B", "Region_C"],
                n_periods=20,
                seed=42,
            )
            assert path.exists()
            import pandas as pd

            df = pd.read_excel(path, engine="openpyxl")
            assert "Region" in df.columns
            assert "Period_0" in df.columns
