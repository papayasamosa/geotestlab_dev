"""Configuration characterisation tests for GeoTestLab.

These tests exercise the live Streamlit application via AppTest and capture
exact configuration defaults — market options, geography levels, strategy
names, and feature-weight sliders.  They do NOT create or update golden files.
They do NOT execute any matching, validation, or evaluation logic.
"""

from __future__ import annotations

import json
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
    """Characterise the app's exact default settings."""

    @pytest.mark.smoke
    def test_default_market_is_uk(self, live_app):
        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) == 1
        assert market_select[0].value == "UK"

    @pytest.mark.smoke
    def test_exact_market_options(self, live_app):
        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) == 1
        options = list(market_select[0].options)
        assert options == [
            "Australia",
            "Canada",
            "Germany",
            "Ireland",
            "Italy",
            "Mexico",
            "New Zealand",
            "Sweden",
            "UK",
        ]

    @pytest.mark.smoke
    def test_default_matching_method(self, live_app):
        method_radio = [r for r in live_app.sidebar.radio if r.label == "Matching method"]
        assert len(method_radio) == 1
        assert method_radio[0].value == "Structural"

    @pytest.mark.smoke
    def test_exact_strategy_options(self, live_app):
        strategy_radio = [r for r in live_app.sidebar.radio if r.label == "Strategy"]
        assert len(strategy_radio) == 1
        options = list(strategy_radio[0].options)
        assert options == [
            "Basic (Fast)",
            "Intermediate (Balanced)",
            "Advanced (Thorough)",
        ]

    @pytest.mark.smoke
    def test_default_strategy(self, live_app):
        strategy_radio = [r for r in live_app.sidebar.radio if r.label == "Strategy"]
        assert len(strategy_radio) == 1
        assert strategy_radio[0].value == "Basic (Fast)"

    @pytest.mark.smoke
    def test_default_geography_level(self, live_app):
        geo_select = [s for s in live_app.sidebar.selectbox if s.label == "Geography Level"]
        assert len(geo_select) == 1
        assert geo_select[0].value == "Local Authority Area"

    @pytest.mark.smoke
    def test_exact_geography_options(self, live_app):
        geo_select = [s for s in live_app.sidebar.selectbox if s.label == "Geography Level"]
        assert len(geo_select) == 1
        options = list(geo_select[0].options)
        assert options == [
            "Local Authority Area",
            "UK Regions",
            "Standard BARB Regions",
            "BBC BARB Regions",
            "ITV Regions",
            "ITL2 Areas",
        ]


# ---------------------------------------------------------------------------
# Feature weight characterisation
# ---------------------------------------------------------------------------


class TestFeatureWeights:
    """Characterise all feature weight sliders."""

    @pytest.mark.smoke
    def test_exact_slider_labels_and_defaults(self, live_app):
        sliders = [s for s in live_app.sidebar.slider]
        labels = [s.label for s in sliders]
        values = [s.value for s in sliders]

        expected_labels = [
            "Population Density",
            "Gender - Female",
            "Gender - Male",
            "Age U16",
            "Age 16-24",
            "Age 25-34",
            "Age 35-49",
            "Age 50-64",
            "Age 65+",
            "Social Grade AB",
            "Social Grade C1",
            "Social Grade C2",
            "Social Grade DE",
        ]
        assert labels == expected_labels, f"Slider labels differ: {labels}"
        for i, v in enumerate(values):
            assert v == 1.0, f"Slider '{labels[i]}' default is {v}, expected 1.0"


# ---------------------------------------------------------------------------
# Market list characterisation (golden comparison)
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
# Fixture factory tests are now in tests/test_ingestion.py
# ---------------------------------------------------------------------------
