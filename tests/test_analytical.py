"""Analytical characterisation tests for GeoTestLab.

These tests exercise the live Streamlit application via AppTest and capture
exact configuration properties.  They do NOT create or update golden files.
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
# Fixture factory tests (deterministic)
# ---------------------------------------------------------------------------


class TestFixtureFactories:
    """Verify the fixture factory functions produce valid, deterministic output."""

    @pytest.mark.smoke
    def test_simple_kpi_deterministic(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        p1 = write_simple_kpi_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        p2 = write_simple_kpi_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        import pandas as pd

        df1 = pd.read_excel(p1, engine="openpyxl")
        df2 = pd.read_excel(p2, engine="openpyxl")
        pd.testing.assert_frame_equal(df1, df2)

    @pytest.mark.smoke
    def test_simple_kpi_structure(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(tmp_path / "test.xlsx", ["R1", "R2"], n_weeks=10, seed=42)
        import pandas as pd

        df = pd.read_excel(path, engine="openpyxl")
        # Exactly 2 non-date columns
        assert "Region" in df.columns
        assert "Metric" in df.columns
        # Date columns should be datetime objects
        date_cols = [c for c in df.columns if c not in ("Region", "Metric")]
        assert len(date_cols) == 10, f"Expected 10 date columns, got {len(date_cols)}"
        import datetime

        assert all(isinstance(c, datetime.datetime) for c in date_cols)
        # Weekly spacing
        diffs = [(date_cols[i] - date_cols[i - 1]).days for i in range(1, len(date_cols))]
        assert all(d == 7 for d in diffs), f"Non-weekly spacing: {diffs}"

    @pytest.mark.smoke
    def test_simple_kpi_edge_cases(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "edge.xlsx",
            ["R1"],
            n_weeks=5,
            seed=42,
            missing_rate=0.5,
            include_unmapped=True,
            include_blank=True,
        )
        import pandas as pd

        df = pd.read_excel(path, engine="openpyxl")
        assert len(df) == 3  # R1 + unmapped + blank
        # Check blank row
        blank_row = df[df["Region"].isna() | (df["Region"] == "")]
        assert len(blank_row) >= 1
        # Check unmapped row
        unmapped = df[df["Region"] == "_UnmappedRegion"]
        assert len(unmapped) == 1

    @pytest.mark.smoke
    def test_aggregated_kpi_structure(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import write_aggregated_kpi_xlsx

        path = write_aggregated_kpi_xlsx(tmp_path / "agg.xlsx", ["R1"], n_weeks=5, seed=42)
        import pandas as pd

        df = pd.read_excel(path, engine="openpyxl")
        # Non-date column order: Store ID, TV Region, Metric, Sub-Region
        assert list(df.columns[:4]) == ["Store ID", "TV Region", "Metric", "Sub-Region"]
        date_cols = [c for c in df.columns if c not in df.columns[:4]]
        assert len(date_cols) == 5

    @pytest.mark.smoke
    def test_aggregated_kpi_edge_cases(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "agg_edge.xlsx",
            ["R1"],
            n_weeks=5,
            seed=42,
            include_blank_agg=True,
            include_duplicates=True,
            missing_rate=1.0,
        )
        import pandas as pd

        df = pd.read_excel(path, engine="openpyxl")
        # Blank aggregation row should be present
        blank = df[df["TV Region"].isna() | (df["TV Region"] == "")]
        assert len(blank) >= 1

    @pytest.mark.smoke
    def test_kpi_pattern_deterministic(self, tmp_path):
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        p1 = write_kpi_pattern_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        p2 = write_kpi_pattern_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        import pandas as pd

        df1 = pd.read_excel(p1, engine="openpyxl")
        df2 = pd.read_excel(p2, engine="openpyxl")
        pd.testing.assert_frame_equal(df1, df2)

    @pytest.mark.smoke
    def test_kpi_pattern_similarity(self, tmp_path):
        """First two regions must be more similar than other pairs."""
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        path = write_kpi_pattern_xlsx(
            tmp_path / "pattern.xlsx",
            ["R1", "R2", "R3", "R4"],
            n_periods=20,
            seed=42,
        )
        import numpy as np
        import pandas as pd

        df = pd.read_excel(path, engine="openpyxl")
        period_cols = [c for c in df.columns if c != "Region"]
        r1 = df[df["Region"] == "R1"][period_cols].values[0]
        r2 = df[df["Region"] == "R2"][period_cols].values[0]
        r3 = df[df["Region"] == "R3"][period_cols].values[0]
        r4 = df[df["Region"] == "R4"][period_cols].values[0]

        d12 = np.mean(np.abs(r1 - r2))
        d13 = np.mean(np.abs(r1 - r3))
        d14 = np.mean(np.abs(r1 - r4))
        assert d12 < d13, f"R1-R2 distance {d12} not less than R1-R3 distance {d13}"
        assert d12 < d14, f"R1-R2 distance {d12} not less than R1-R4 distance {d14}"
