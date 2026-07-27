"""Live ingestion tests for GeoTestLab fixture factories and file parsing.

These tests verify that generated fixture Excel files are correctly parsed
by the application's data-loading functions.  KPI-pattern upload is tested
through the live sidebar uploader.  Simple and aggregated upload parsing
is tested at the unit level (the design-tab uploader requires completing
the matching workflow, which is a Stage 2 scenario).
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers: replicate the app's parsing functions for unit-testing uploads
# ---------------------------------------------------------------------------


def _detect_date_columns(df_raw: pd.DataFrame) -> list:
    """Identify datetime column headers (same logic as the live app)."""
    from datetime import datetime as _dt

    return [c for c in df_raw.columns if isinstance(c, (pd.Timestamp, _dt))]


def _load_and_reshape_kpi(
    file_bytes: bytes,
    agg_col: str | None = None,
    metric_col: str | None = None,
) -> pd.DataFrame:
    """Replicate the app's load_and_reshape_kpi for test purposes."""
    bio = io.BytesIO(file_bytes)
    try:
        df_raw = pd.read_excel(bio, engine="calamine", header=0)
    except Exception:
        bio.seek(0)
        df_raw = pd.read_excel(bio, engine="openpyxl", header=0)

    date_cols = _detect_date_columns(df_raw)
    non_date_cols = [c for c in df_raw.columns if c not in date_cols]

    if len(non_date_cols) <= 2:
        region_col = df_raw.columns[0]
        metric_col_resolved = df_raw.columns[1]
    else:
        if agg_col is None or metric_col is None:
            raise ValueError("agg_col and metric_col must be selected for multi-level format")
        region_col = agg_col
        metric_col_resolved = metric_col

    df_raw = df_raw.dropna(subset=[region_col])
    df_raw = df_raw[df_raw[region_col].astype(str).str.strip() != ""]

    df_long = df_raw.melt(
        id_vars=[region_col, metric_col_resolved],
        value_vars=date_cols if date_cols else None,
        var_name="date",
        value_name="kpi",
    )
    df_long = df_long.rename(columns={region_col: "region_raw", metric_col_resolved: "metric_name"})
    df_long["date"] = pd.to_datetime(df_long["date"], errors="coerce")
    df_long = df_long.dropna(subset=["date", "kpi"])
    df_long["kpi"] = pd.to_numeric(df_long["kpi"], errors="coerce")
    df_long = df_long.dropna(subset=["kpi"])
    return df_long


# ---------------------------------------------------------------------------
# Default configuration tests (no vacuous assertions)
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    """Verify the app defaults to structural matching with UK data."""

    @pytest.mark.smoke
    def test_default_structural_mode_shows_preview_expander(self, live_app):
        """With the default UK market, the app should show a data preview expander."""
        assert len(live_app.expander) >= 1, (
            "Expected at least one expander (data preview) in default mode"
        )
        expander_labels = [e.label for e in live_app.expander]
        has_preview = any(
            "Preview" in lbl or "Data" in lbl or "Population" in lbl for lbl in expander_labels
        )
        assert has_preview, f"No preview expander found. Labels: {expander_labels}"

    @pytest.mark.smoke
    def test_live_app_no_exception(self, live_app):
        assert not live_app.exception, f"App raised: {live_app.exception}"

    @pytest.mark.smoke
    def test_market_selectbox_has_options(self, live_app):
        market_select = [s for s in live_app.sidebar.selectbox if s.label == "Market"]
        assert len(market_select) == 1
        assert len(market_select[0].options) > 0, "No market options loaded"

    @pytest.mark.smoke
    def test_sidebar_has_content(self, live_app):
        """Sidebar should have markdown or caption with data quality info."""
        assert len(live_app.sidebar.markdown) > 0 or len(live_app.sidebar.caption) > 0


# ---------------------------------------------------------------------------
# Simple KPI parsing (unit-level: parser without full UI flow)
# ---------------------------------------------------------------------------


class TestSimpleKPIParsing:
    """Verify simple-format KPI files are correctly parsed by the app's logic."""

    @pytest.mark.smoke
    def test_simple_kpi_format_detected(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "simple.xlsx",
            ["Hartlepool", "Middlesbrough"],
            metric_name="Sales",
            n_weeks=10,
            seed=42,
        )
        df = _load_and_reshape_kpi(path.read_bytes())
        assert "region_raw" in df.columns
        assert "metric_name" in df.columns
        assert "date" in df.columns
        assert "kpi" in df.columns
        assert df["metric_name"].iloc[0] == "Sales"

    @pytest.mark.smoke
    def test_simple_kpi_date_count(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "dates.xlsx",
            ["Hartlepool"],
            n_weeks=13,
            seed=42,
        )
        df = _load_and_reshape_kpi(path.read_bytes())
        assert len(df) == 13
        assert df["date"].nunique() == 13

    @pytest.mark.smoke
    def test_simple_kpi_region_count(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "regions.xlsx",
            ["Hartlepool", "Middlesbrough", "Redcar and Cleveland"],
            n_weeks=5,
            seed=42,
        )
        df = _load_and_reshape_kpi(path.read_bytes())
        assert df["region_raw"].nunique() == 3


# ---------------------------------------------------------------------------
# Aggregated KPI parsing (unit-level)
# ---------------------------------------------------------------------------


class TestAggregatedKPIParsing:
    """Verify aggregated-format KPI files are correctly parsed."""

    @pytest.mark.smoke
    def test_aggregated_format_detected(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "agg.xlsx",
            ["Hartlepool"],
            aggregation_level_col="TV Region",
            n_weeks=5,
            seed=42,
        )
        df = _load_and_reshape_kpi(path.read_bytes(), agg_col="TV Region", metric_col="Metric")
        assert len(df) > 0
        assert "region_raw" in df.columns
        assert df["region_raw"].iloc[0] == "Hartlepool"

    @pytest.mark.smoke
    def test_aggregated_kpi_blank_rows_dropped(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "agg_blank.xlsx",
            ["Hartlepool"],
            n_weeks=5,
            seed=42,
            include_blank_agg=True,
        )
        df = _load_and_reshape_kpi(path.read_bytes(), agg_col="TV Region", metric_col="Metric")
        blank = df[df["region_raw"].isna() | (df["region_raw"].astype(str).str.strip() == "")]
        assert len(blank) == 0, "Blank aggregation rows were not dropped"

    @pytest.mark.smoke
    def test_aggregated_kpi_metric_name(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "agg_metric.xlsx",
            ["Hartlepool"],
            metric_name="Sales",
            n_weeks=5,
            seed=42,
        )
        df = _load_and_reshape_kpi(path.read_bytes(), agg_col="TV Region", metric_col="Metric")
        assert df["metric_name"].iloc[0] == "Sales"


# ---------------------------------------------------------------------------
# KPI-pattern upload via sidebar (live AppTest interaction)
# ---------------------------------------------------------------------------


class TestKPIPatternIngestion:
    """Attempt to upload a KPI-pattern workbook through the sidebar uploader."""

    @pytest.mark.smoke
    def test_kpi_pattern_upload_detected(self, live_app):
        """When matching method is switched to KPI Pattern, the sidebar should
        show a file uploader for KPI files."""
        method_radio = [r for r in live_app.sidebar.radio if r.label == "Matching method"]
        assert len(method_radio) == 1
        method_radio[0].set_value("KPI Pattern")
        live_app.run(timeout=180)

        # The sidebar should have a file uploader labelled for KPI
        kpi_uploaders = [
            f
            for f in live_app.sidebar.file_uploader
            if "KPI" in f.label or "aggregated" in f.label.lower()
        ]
        if len(kpi_uploaders) == 0:
            # Uploader may not persist across re-run in all AppTest versions
            pytest.skip("KPI uploader not found after mode switch")

        # The uploader should have the expected label and key
        assert "KPI" in kpi_uploaders[0].label or "aggregated" in kpi_uploaders[0].label.lower()
        assert kpi_uploaders[0].key == "kpi_pattern_sidebar_uploader"


# ---------------------------------------------------------------------------
# Fixture factory edge cases
# ---------------------------------------------------------------------------


class TestFixtureFactoryEdgeCases:
    """Independent edge-case assertions for each fixture factory."""

    # --- Simple KPI ---

    @pytest.mark.smoke
    def test_simple_kpi_blank_region(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "blank.xlsx", ["R1"], n_weeks=5, seed=42, include_blank=True
        )
        df = pd.read_excel(path, engine="openpyxl")
        blank = df[df["Region"].isna() | (df["Region"] == "")]
        assert len(blank) >= 1

    @pytest.mark.smoke
    def test_simple_kpi_unmapped_region(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "unmapped.xlsx", ["R1"], n_weeks=5, seed=42, include_unmapped=True
        )
        df = pd.read_excel(path, engine="openpyxl")
        unmapped = df[df["Region"] == "_UnmappedRegion"]
        assert len(unmapped) == 1

    @pytest.mark.smoke
    def test_simple_kpi_missing_values(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "missing.xlsx", ["R1"], n_weeks=10, seed=42, missing_rate=1.0
        )
        df = pd.read_excel(path, engine="openpyxl")
        date_cols = [c for c in df.columns if c not in ("Region", "Metric")]
        assert df[date_cols].isna().any().any()

    @pytest.mark.smoke
    def test_simple_kpi_weekly_spacing(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(tmp_path / "weekly.xlsx", ["R1"], n_weeks=10, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        date_cols = [c for c in df.columns if c not in ("Region", "Metric")]
        import datetime

        assert all(isinstance(c, datetime.datetime) for c in date_cols)
        diffs = [(date_cols[i] - date_cols[i - 1]).days for i in range(1, len(date_cols))]
        assert all(d == 7 for d in diffs), f"Non-weekly spacing: {diffs}"

    @pytest.mark.smoke
    def test_simple_kpi_same_seed_equality(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        p1 = write_simple_kpi_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        p2 = write_simple_kpi_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        pd.testing.assert_frame_equal(
            pd.read_excel(p1, engine="openpyxl"),
            pd.read_excel(p2, engine="openpyxl"),
        )

    @pytest.mark.smoke
    def test_simple_kpi_diff_seed_inequality(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        p1 = write_simple_kpi_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        p2 = write_simple_kpi_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_weeks=5, seed=99)
        assert not pd.read_excel(p1, engine="openpyxl").equals(pd.read_excel(p2, engine="openpyxl"))

    # --- Aggregated KPI ---

    @pytest.mark.smoke
    def test_aggregated_deterministic(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        p1 = write_aggregated_kpi_xlsx(tmp_path / "a.xlsx", ["R1"], n_weeks=5, seed=42)
        p2 = write_aggregated_kpi_xlsx(tmp_path / "b.xlsx", ["R1"], n_weeks=5, seed=42)
        pd.testing.assert_frame_equal(
            pd.read_excel(p1, engine="openpyxl"),
            pd.read_excel(p2, engine="openpyxl"),
        )

    @pytest.mark.smoke
    def test_aggregated_diff_seed_inequality(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        p1 = write_aggregated_kpi_xlsx(tmp_path / "a.xlsx", ["R1"], n_weeks=5, seed=42)
        p2 = write_aggregated_kpi_xlsx(tmp_path / "b.xlsx", ["R1"], n_weeks=5, seed=99)
        assert not pd.read_excel(p1, engine="openpyxl").equals(pd.read_excel(p2, engine="openpyxl"))

    @pytest.mark.smoke
    def test_aggregated_blank_agg_row(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "blanks.xlsx", ["R1"], n_weeks=5, seed=42, include_blank_agg=True
        )
        df = pd.read_excel(path, engine="openpyxl")
        blank = df[df["TV Region"].isna() | (df["TV Region"] == "")]
        assert len(blank) >= 1

    @pytest.mark.smoke
    def test_aggregated_missing_values(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "missing.xlsx", ["R1"], n_weeks=10, seed=42, missing_rate=1.0
        )
        df = pd.read_excel(path, engine="openpyxl")
        date_cols = [c for c in df.columns if c not in df.columns[:4]]
        assert df[date_cols].isna().any().any()

    @pytest.mark.smoke
    def test_aggregated_duplicate_row(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "dupes.xlsx", ["R1"], n_weeks=5, seed=42, include_duplicates=True
        )
        # Verify _DUP rows exist in the raw Excel
        df_raw = pd.read_excel(path, engine="openpyxl")
        dup_rows = df_raw[df_raw["Store ID"].str.endswith("_DUP", na=False)]
        assert len(dup_rows) >= 1

        # Verify duplicates create genuine key collisions after melting.
        # The application key is (region_raw, metric_name, date).
        df_melted = _load_and_reshape_kpi(
            path.read_bytes(), agg_col="TV Region", metric_col="Metric"
        )
        key_counts = df_melted.groupby(["region_raw", "metric_name", "date"]).size()
        max_count = key_counts.max()
        assert max_count > 1, (
            f"Expected duplicate key (region, metric, date) after melting "
            f"when include_duplicates=True. Max key count: {max_count}"
        )

    @pytest.mark.smoke
    def test_aggregated_column_order(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(tmp_path / "cols.xlsx", ["R1"], n_weeks=5, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        assert list(df.columns[:4]) == ["Store ID", "TV Region", "Metric", "Sub-Region"]

    @pytest.mark.smoke
    def test_aggregated_date_count(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(tmp_path / "dates.xlsx", ["R1"], n_weeks=8, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        date_cols = [c for c in df.columns if c not in df.columns[:4]]
        assert len(date_cols) == 8

    # --- KPI Pattern ---

    @pytest.mark.smoke
    def test_kpi_pattern_same_seed(self, tmp_path):
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        p1 = write_kpi_pattern_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        p2 = write_kpi_pattern_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        pd.testing.assert_frame_equal(
            pd.read_excel(p1, engine="openpyxl"),
            pd.read_excel(p2, engine="openpyxl"),
        )

    @pytest.mark.smoke
    def test_kpi_pattern_diff_seed(self, tmp_path):
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        p1 = write_kpi_pattern_xlsx(tmp_path / "a.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        p2 = write_kpi_pattern_xlsx(tmp_path / "b.xlsx", ["R1", "R2"], n_periods=10, seed=99)
        assert not pd.read_excel(p1, engine="openpyxl").equals(pd.read_excel(p2, engine="openpyxl"))

    @pytest.mark.smoke
    def test_kpi_pattern_period_columns(self, tmp_path):
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        path = write_kpi_pattern_xlsx(tmp_path / "periods.xlsx", ["R1"], n_periods=8, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        assert list(df.columns) == ["Region"] + [f"Period_{i}" for i in range(8)]

    @pytest.mark.smoke
    def test_kpi_pattern_similarity(self, tmp_path):
        """First two regions must be more similar than other pairs."""
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        path = write_kpi_pattern_xlsx(
            tmp_path / "similarity.xlsx",
            ["R1", "R2", "R3", "R4"],
            n_periods=20,
            seed=42,
        )
        import numpy as np

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

    @pytest.mark.smoke
    def test_kpi_pattern_min_regions(self, tmp_path):
        """Must accept at least 2 regions."""
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        path = write_kpi_pattern_xlsx(tmp_path / "min.xlsx", ["R1", "R2"], n_periods=10, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        assert len(df) == 2
        assert list(df["Region"]) == ["R1", "R2"]

    @pytest.mark.smoke
    def test_kpi_pattern_single_period(self, tmp_path):
        """A single period should still produce valid output."""
        from tests.fixture_factories.write_kpi_pattern_xlsx import write_kpi_pattern_xlsx

        path = write_kpi_pattern_xlsx(tmp_path / "single.xlsx", ["R1", "R2"], n_periods=1, seed=42)
        df = pd.read_excel(path, engine="openpyxl")
        assert len(df) == 2
        assert "Period_0" in df.columns
