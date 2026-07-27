"""Live ingestion tests for GeoTestLab fixture factories and file parsing.

These tests exercise the PRODUCTION ingestion code in
``geotestlab.data.ingestion`` directly — no copied/reimplemented parser
logic lives in this file. KPI-pattern upload is tested through the live
sidebar uploader (real AppTest upload, not skipped). Simple and aggregated
upload parsing is tested at the unit level (the design-tab uploader
requires completing the matching workflow, which is a Stage 2 scenario).
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from geotestlab.data.exceptions import (
    MissingIdentifierColumnsError,
    NoRetainedKPIObservationsError,
    UnreadableWorkbookError,
    UnresolvedAggregationColumnError,
    UnresolvedMetricColumnError,
)
from geotestlab.data.ingestion import load_and_reshape_kpi

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, **kwargs):
    """Call the production ingestion entry point on a fixture file's bytes."""
    return load_and_reshape_kpi(io.BytesIO(path.read_bytes()), **kwargs)


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
# Simple KPI parsing — production geotestlab.data.ingestion.load_and_reshape_kpi
# ---------------------------------------------------------------------------


class TestSimpleKPIParsing:
    """Verify simple-format KPI files are correctly parsed by production ingestion."""

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
        parsed = _load(path)
        df = parsed.data
        assert "region_raw" in df.columns
        assert "metric_name" in df.columns
        assert "date" in df.columns
        assert "kpi" in df.columns
        assert df["metric_name"].iloc[0] == "Sales"
        assert parsed.quality.parsed_layout == "simple"
        assert parsed.quality.rows_read == 2
        assert parsed.quality.rows_retained == len(df)
        assert parsed.quality.metric_names == ("Sales",)
        assert parsed.quality.blocking_errors == ()

    @pytest.mark.smoke
    def test_simple_kpi_date_count(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "dates.xlsx",
            ["Hartlepool"],
            n_weeks=13,
            seed=42,
        )
        parsed = _load(path)
        df = parsed.data
        assert len(df) == 13
        assert df["date"].nunique() == 13
        assert parsed.quality.date_count == 13
        assert parsed.quality.invalid_date_values == 0

    @pytest.mark.smoke
    def test_simple_kpi_region_count(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "regions.xlsx",
            ["Hartlepool", "Middlesbrough", "Redcar and Cleveland"],
            n_weeks=5,
            seed=42,
        )
        parsed = _load(path)
        assert parsed.data["region_raw"].nunique() == 3
        assert len(parsed.quality.raw_regions) == 3

    @pytest.mark.smoke
    def test_simple_kpi_blank_region_dropped_and_reported(self, tmp_path):
        """Blank region rows are dropped from retained data but counted in the report."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "blank.xlsx", ["Hartlepool"], n_weeks=5, seed=42, include_blank=True
        )
        parsed = _load(path)
        assert "" not in parsed.data["region_raw"].values
        assert parsed.quality.blank_region_rows > 0
        assert any("blank region" in w for w in parsed.quality.warnings)

    @pytest.mark.smoke
    def test_simple_kpi_unmapped_region_passed_through(self, tmp_path):
        """Ingestion doesn't validate region names against a geography list —
        that's build_region_mapping's job, downstream of this module."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "unmapped.xlsx", ["Hartlepool"], n_weeks=5, seed=42, include_unmapped=True
        )
        parsed = _load(path)
        assert "_UnmappedRegion" in parsed.data["region_raw"].values
        assert "_UnmappedRegion" in parsed.quality.raw_regions

    @pytest.mark.smoke
    def test_simple_kpi_missing_values_dropped_and_counted(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "missing.xlsx", ["Hartlepool"], n_weeks=20, seed=42, missing_rate=0.5
        )
        parsed = _load(path)
        assert parsed.data["kpi"].isna().sum() == 0, "Missing KPI rows must not be retained"
        assert parsed.quality.missing_kpi_values > 0
        assert parsed.quality.rows_retained == len(parsed.data)
        assert parsed.quality.rows_retained < parsed.quality.rows_read * 20


# ---------------------------------------------------------------------------
# Aggregated KPI parsing — production ingestion
# ---------------------------------------------------------------------------


class TestAggregatedKPIParsing:
    """Verify aggregated-format KPI files are correctly parsed by production ingestion."""

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
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        assert len(parsed.data) > 0
        assert "region_raw" in parsed.data.columns
        assert parsed.data["region_raw"].iloc[0] == "Hartlepool"
        assert parsed.quality.parsed_layout == "aggregated"

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
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        df = parsed.data
        blank = df[df["region_raw"].isna() | (df["region_raw"].astype(str).str.strip() == "")]
        assert len(blank) == 0, "Blank aggregation rows were not dropped"
        assert parsed.quality.blank_region_rows > 0

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
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        assert parsed.data["metric_name"].iloc[0] == "Sales"
        assert parsed.quality.metric_names == ("Sales",)

    @pytest.mark.smoke
    def test_aggregated_kpi_duplicate_keys_counted(self, tmp_path):
        """Duplicate (region, metric, date) keys are retained (not silently
        deduplicated) and counted in the quality report."""
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(
            tmp_path / "dupes.xlsx", ["Hartlepool"], n_weeks=5, seed=42, include_duplicates=True
        )
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        key_counts = parsed.data.groupby(["region_raw", "metric_name", "date"]).size()
        assert key_counts.max() > 1, "Expected a duplicate (region, metric, date) key"
        assert parsed.quality.duplicate_keys > 0
        assert any("duplicate" in w for w in parsed.quality.warnings)


# ---------------------------------------------------------------------------
# Domain exceptions — malformed / ambiguous inputs
# ---------------------------------------------------------------------------


class TestIngestionDomainExceptions:
    """Each malformed-input scenario raises a distinct, catchable domain exception."""

    @pytest.mark.smoke
    def test_unreadable_workbook_raises(self, tmp_path):
        bad_path = tmp_path / "not_really_excel.xlsx"
        bad_path.write_bytes(b"this is not a valid xlsx workbook")
        with pytest.raises(UnreadableWorkbookError):
            _load(bad_path)

    @pytest.mark.smoke
    def test_unresolved_aggregation_column_raises(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(tmp_path / "agg.xlsx", ["Hartlepool"], n_weeks=5, seed=42)
        with pytest.raises(UnresolvedAggregationColumnError):
            _load(path, agg_col=None, metric_col="Metric")

    @pytest.mark.smoke
    def test_unresolved_metric_column_raises(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(tmp_path / "agg.xlsx", ["Hartlepool"], n_weeks=5, seed=42)
        with pytest.raises(UnresolvedMetricColumnError):
            _load(path, agg_col="TV Region", metric_col=None)

    @pytest.mark.smoke
    def test_missing_identifier_columns_raises(self, tmp_path):
        """A file with fewer than 2 non-date columns can't resolve a region
        column and a metric column."""
        dates = pd.date_range("2026-01-04", periods=5, freq="W")
        df = pd.DataFrame({d: [1.0, 2.0] for d in dates})
        path = tmp_path / "no_identifiers.xlsx"
        df.to_excel(path, index=False, engine="openpyxl")
        with pytest.raises(MissingIdentifierColumnsError):
            _load(path)

    @pytest.mark.smoke
    def test_no_retained_kpi_observations_raises(self, tmp_path):
        """Every KPI value missing leaves nothing to retain."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "all_missing.xlsx", ["R1"], n_weeks=10, seed=42, missing_rate=1.0
        )
        with pytest.raises(NoRetainedKPIObservationsError):
            _load(path)


# ---------------------------------------------------------------------------
# KPI-pattern upload via sidebar (real live AppTest interaction)
# ---------------------------------------------------------------------------


class TestKPIPatternIngestion:
    """Upload a KPI-pattern-mode workbook through the live sidebar uploader."""

    @pytest.mark.smoke
    def test_kpi_pattern_upload_detected(self, tmp_path):
        from streamlit.testing.v1 import AppTest

        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        # 1. Fresh app.
        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=180)
        assert not app.exception

        # 2. Switch to KPI Pattern.
        method_radio = [r for r in app.sidebar.radio if r.label == "Matching method"]
        assert len(method_radio) == 1
        method_radio[0].set_value("KPI Pattern")
        app.run(timeout=180)
        assert not app.exception

        # 3. Assert the uploader exists.
        kpi_uploaders = [
            f for f in app.sidebar.file_uploader if f.key == "kpi_pattern_sidebar_uploader"
        ]
        assert len(kpi_uploaders) == 1, (
            f"KPI pattern uploader not found. Uploaders: "
            f"{[f.key for f in app.sidebar.file_uploader]}"
        )

        # 4. Upload a generated workbook. The sidebar's KPI Pattern mode expects the
        # same shape as the "aggregated" format: a raw key column, one or more
        # aggregation-level columns, a Metric column, and date columns.
        path = write_aggregated_kpi_xlsx(
            tmp_path / "kpi_pattern.xlsx",
            ["RegionA", "RegionB", "RegionC"],
            aggregation_level_col="TV Region",
            n_weeks=10,
            seed=7,
        )
        kpi_uploaders[0].set_value(
            (
                "kpi_pattern.xlsx",
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )

        # 5. Rerun.
        app.run(timeout=180)
        assert not app.exception

        # 6. Assert region (aggregation-level) and period (date) detection.
        agg_selects = [s for s in app.sidebar.selectbox if s.key == "kpi_pattern_agg_col_sidebar"]
        assert len(agg_selects) == 1, "Aggregation-level selectbox did not appear after upload"
        assert "TV Region" in agg_selects[0].options

        start_date_selects = [
            s for s in app.sidebar.selectbox if s.key == "kpi_pattern_date_start_sidebar"
        ]
        end_date_selects = [
            s for s in app.sidebar.selectbox if s.key == "kpi_pattern_date_end_sidebar"
        ]
        assert len(start_date_selects) == 1
        assert len(end_date_selects) == 1
        assert len(start_date_selects[0].options) == 10, "Expected 10 detected period/date options"

        # 7. No exception.
        assert not app.exception


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

        # Verify duplicates create genuine key collisions after melting, via
        # production ingestion. The application key is (region_raw, metric_name, date).
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        key_counts = parsed.data.groupby(["region_raw", "metric_name", "date"]).size()
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
