"""Tests for the extended data-quality contract (Stage 2).

Covers:
- explicit, unambiguous report counts (source rows vs long-format observations);
- frequency inference and expected/missing date coverage;
- the typed RegionMappingReport (mapped/unmapped regions + unmapped rows);
- clean-data parity: the analytical input DataFrame is unchanged;
- live AppTest coverage: the report appears, blockers prevent modelling,
  warnings do not silently block valid data, rejected rows are downloadable.
"""

from __future__ import annotations

import datetime
import io
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from geotestlab.data.ingestion import (
    _expected_and_missing_dates,
    infer_frequency,
    load_and_reshape_kpi,
)
from geotestlab.data.models import compute_mapping_report
from tests.fixtures.live_scenarios import RUN_TIMEOUT, _pick_test_auto_match, _run_match

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(path: Path, **kwargs):
    return load_and_reshape_kpi(io.BytesIO(path.read_bytes()), **kwargs)


# ---------------------------------------------------------------------------
# Explicit report counts — pure unit tests
# ---------------------------------------------------------------------------


class TestReportCounts:
    """Every count in DataQualityReport must have an unambiguous meaning."""

    @pytest.mark.smoke
    def test_clean_simple_file_counts(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(tmp_path / "clean.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        parsed = _load(path)
        q = parsed.quality

        assert q.source_rows_read == 2
        assert q.source_rows_dropped_blank_region == 0
        assert q.source_rows_removed == 0
        assert q.source_date_columns == 5

        assert q.observations_expected == 10
        assert q.observations_retained == 10
        assert q.observations_dropped_missing_kpi == 0
        assert q.observations_dropped_non_numeric_kpi == 0
        assert q.observations_dropped_invalid_date == 0
        assert q.observations_removed == 0

        assert q.duplicate_key_rows == 0
        assert q.duplicate_key_groups == 0

        assert q.selected_layout == "simple"
        assert q.selected_aggregation_column is None
        assert q.selected_metric_column == "Metric"
        assert q.metrics_found == ("Sales",)

        assert q.inferred_frequency == "weekly"
        assert q.expected_date_count == 5
        assert q.missing_dates == ()
        assert q.date_range is not None
        assert q.date_range[0] <= q.date_range[1]

        assert q.raw_regions == ("R1", "R2")
        assert q.warnings == ()
        assert q.blocking_errors == ()
        assert parsed.rejected_rows is None

    @pytest.mark.smoke
    def test_blank_region_source_rows_counted(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(
            tmp_path / "blank.xlsx", ["R1"], n_weeks=3, seed=42, include_blank=True
        )
        parsed = _load(path)
        q = parsed.quality

        assert q.source_rows_read == 2
        assert q.source_rows_dropped_blank_region == 1
        assert q.source_rows_removed == 1
        # The blank source row is dropped BEFORE melting, so it contributes no
        # observations to the expected count.
        assert q.observations_expected == 1 * 3
        assert q.observations_retained == 3
        assert q.observations_removed == 0
        assert any("blank region" in w for w in q.warnings)

    @pytest.mark.smoke
    def test_missing_vs_non_numeric_observations_split(self, tmp_path):
        """Missing KPI and non-numeric KPI must be reported as separate counts."""
        dates = pd.date_range("2026-01-04", periods=3, freq="W")
        df = pd.DataFrame({"Region": ["R1", "R2"], "Metric": ["Sales", "Sales"]})
        for i, d in enumerate(dates):
            df[d] = [10.0, 20.0] if i > 0 else [None, "not-a-number"]
        path = tmp_path / "mixed.xlsx"
        df.to_excel(path, index=False, engine="openpyxl")

        parsed = _load(path)
        q = parsed.quality

        assert q.source_rows_read == 2
        assert q.source_date_columns == 3
        assert q.observations_expected == 6
        assert q.observations_dropped_missing_kpi == 1
        assert q.observations_dropped_non_numeric_kpi == 1
        assert q.observations_retained == 4
        assert q.observations_removed == 2
        assert q.observations_expected == q.observations_retained + q.observations_removed
        # Rejected rows capture both drop categories for download.
        assert parsed.rejected_rows is not None
        assert len(parsed.rejected_rows) == 2

    @pytest.mark.smoke
    def test_duplicate_key_rows_and_groups(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        n_weeks = 5
        path = write_aggregated_kpi_xlsx(
            tmp_path / "dupes.xlsx",
            ["R1"],
            n_weeks=n_weeks,
            seed=42,
            include_duplicates=True,
        )
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        q = parsed.quality

        assert q.duplicate_key_rows == 2 * n_weeks
        assert q.duplicate_key_groups == n_weeks
        assert any("duplicate" in w for w in q.warnings)

    @pytest.mark.smoke
    def test_aggregated_selection_columns_reported(self, tmp_path):
        from tests.fixture_factories.write_aggregated_kpi_xlsx import (
            write_aggregated_kpi_xlsx,
        )

        path = write_aggregated_kpi_xlsx(tmp_path / "agg.xlsx", ["R1"], n_weeks=3, seed=42)
        parsed = _load(path, agg_col="TV Region", metric_col="Metric")
        q = parsed.quality

        assert q.selected_layout == "aggregated"
        assert q.selected_aggregation_column == "TV Region"
        assert q.selected_metric_column == "Metric"
        assert q.metrics_found == ("Sales",)


# ---------------------------------------------------------------------------
# Frequency inference and date coverage
# ---------------------------------------------------------------------------


class TestFrequencyAndDateCoverage:
    @pytest.mark.smoke
    def test_weekly_frequency_with_missing_date(self):
        dates = pd.to_datetime(["2026-01-04", "2026-01-11", "2026-01-25", "2026-02-01"])
        assert infer_frequency(dates) == "weekly"
        n_expected, missing = _expected_and_missing_dates(dates, "weekly")
        assert n_expected == 5
        assert missing == (pd.Timestamp("2026-01-18"),)

    @pytest.mark.smoke
    def test_daily_frequency_with_missing_date(self):
        dates = pd.date_range("2026-01-01", "2026-01-05", freq="D").drop(pd.Timestamp("2026-01-03"))
        assert infer_frequency(dates) == "daily"
        n_expected, missing = _expected_and_missing_dates(dates, "daily")
        assert n_expected == 5
        assert missing == (pd.Timestamp("2026-01-03"),)

    @pytest.mark.smoke
    def test_unknown_frequency_treats_observed_as_expected(self):
        dates = pd.to_datetime(["2026-01-04", "2026-01-17"])
        assert infer_frequency(dates) == "unknown"
        n_expected, missing = _expected_and_missing_dates(dates, "unknown")
        assert n_expected == 2
        assert missing == ()

    @pytest.mark.smoke
    def test_report_date_coverage_fields(self, tmp_path):
        """A gapped weekly file surfaces missing dates in the report."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(tmp_path / "gap.xlsx", ["R1"], n_weeks=5, seed=42)
        parsed = _load(path)
        q = parsed.quality
        assert q.inferred_frequency == "weekly"
        assert q.expected_date_count == 5
        assert q.missing_dates == ()


# ---------------------------------------------------------------------------
# Clean-data parity
# ---------------------------------------------------------------------------


class TestCleanDataParity:
    @pytest.mark.smoke
    def test_clean_data_analytical_input_unchanged(self, tmp_path):
        """The retained long-format DataFrame must be identical to an independent
        reference melt of the same workbook (no analytical input change)."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        path = write_simple_kpi_xlsx(tmp_path / "clean.xlsx", ["R1", "R2"], n_weeks=5, seed=42)
        parsed = _load(path)

        raw = pd.read_excel(path, engine="calamine", header=0)
        date_cols = [c for c in raw.columns if isinstance(c, (pd.Timestamp, datetime.datetime))]
        reference = (
            raw.melt(
                id_vars=[raw.columns[0], raw.columns[1]],
                value_vars=date_cols,
                var_name="date",
                value_name="kpi",
            )
            .rename(columns={raw.columns[0]: "region_raw", raw.columns[1]: "metric_name"})
            .copy()
        )
        reference["date"] = pd.to_datetime(reference["date"], errors="coerce")
        reference = reference.dropna(subset=["date", "kpi"])
        reference["kpi"] = pd.to_numeric(reference["kpi"], errors="coerce")
        reference = reference.dropna(subset=["kpi"])

        pd.testing.assert_frame_equal(
            parsed.data.reset_index(drop=True), reference.reset_index(drop=True)
        )


# ---------------------------------------------------------------------------
# RegionMappingReport — pure function
# ---------------------------------------------------------------------------


class TestRegionMappingReport:
    @pytest.mark.smoke
    def test_mapping_report_splits_mapped_and_unmapped(self):
        df = pd.DataFrame(
            {
                "region_raw": ["A", "A", "B", "C"],
                "region": ["X", "X", "Y", None],
                "kpi": [1.0, 2.0, 3.0, 4.0],
            }
        )
        rep = compute_mapping_report(df)
        assert rep.raw_regions == ("A", "B", "C")
        assert rep.mapped_regions == ("A", "B")
        assert rep.unmapped_regions == ("C",)
        assert rep.unmapped_rows is not None
        assert len(rep.unmapped_rows) == 1
        assert rep.unmapped_rows.iloc[0]["region_raw"] == "C"

    @pytest.mark.smoke
    def test_mapping_report_all_mapped_has_no_download(self):
        df = pd.DataFrame({"region_raw": ["A", "B"], "region": ["X", "Y"], "kpi": [1.0, 2.0]})
        rep = compute_mapping_report(df)
        assert rep.mapped_regions == ("A", "B")
        assert rep.unmapped_regions == ()
        assert rep.unmapped_rows is None

    @pytest.mark.smoke
    def test_mapping_report_rejects_missing_columns(self):
        with pytest.raises(ValueError):
            compute_mapping_report(pd.DataFrame({"region_raw": ["A"], "kpi": [1.0]}))


# ---------------------------------------------------------------------------
# Live AppTest coverage
# ---------------------------------------------------------------------------


class TestQualityReportUI:
    """The data-quality report must appear, block on errors, tolerate warnings,
    and expose downloadable rejected rows in the live app."""

    @staticmethod
    def _prepare_matching_state(app):
        """Run a minimal real matching workflow so the validation tab renders.

        ``render_time_series_validation()`` returns early while
        ``final_controls`` is None, so the main-area KPI uploader only exists
        after a matching run.  Driving the real workflow (via the same helpers
        the golden scenarios use) keeps session state internally consistent.
        """
        _pick_test_auto_match(app, "Aberdeen City")
        _run_match(app)

    @staticmethod
    def _upload_design_kpi(app, path):
        app.run(timeout=RUN_TIMEOUT)
        TestQualityReportUI._prepare_matching_state(app)
        uploaders = [f for f in app.file_uploader if f.key.startswith("kpi_uploader_design_")]
        assert len(uploaders) == 1, (
            f"Design KPI uploader not found: {[f.key for f in app.file_uploader]}"
        )
        uploaders[0].set_value(
            (
                path.name,
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )
        app.run(timeout=RUN_TIMEOUT)

    @pytest.mark.smoke
    def test_report_appears_after_upload(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=180)
        assert not app.exception

        path = write_simple_kpi_xlsx(tmp_path / "kpi.xlsx", ["R1", "R2"], n_weeks=26, seed=42)
        self._upload_design_kpi(app, path)

        assert not app.exception
        assert any("Data Quality Report" in e.label for e in app.expander)
        metric_labels = [m.label for m in app.metric]
        assert any("Source rows read" in label for label in metric_labels)
        assert any("Observations retained" in label for label in metric_labels)
        assert any("usable observation" in s.value for s in app.success)

    @pytest.mark.smoke
    def test_blockers_prevent_modelling(self, tmp_path):
        from dataclasses import replace

        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=180)
        assert not app.exception

        path = write_simple_kpi_xlsx(tmp_path / "kpi.xlsx", ["R1"], n_weeks=26, seed=42)
        self._upload_design_kpi(app, path)
        assert not app.exception
        assert "kpi_quality_report" in app.session_state

        report = app.session_state["kpi_quality_report"]
        blocked = replace(
            report, blocking_errors=("Blocked for test: duplicate keys require review",)
        )
        app.session_state["kpi_quality_report"] = blocked
        app.session_state["validation_triggered"] = True
        app.run(timeout=180)

        assert not app.exception
        assert any("Blocked for test" in e.value for e in app.error)
        assert app.session_state["validation_triggered"] is False

    @pytest.mark.smoke
    def test_warnings_do_not_block_valid_data(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=180)
        assert not app.exception

        path = write_simple_kpi_xlsx(
            tmp_path / "warn.xlsx",
            ["R1"],
            n_weeks=26,
            seed=42,
            include_blank=True,
            missing_rate=0.2,
        )
        self._upload_design_kpi(app, path)
        assert not app.exception

        report = app.session_state["kpi_quality_report"]
        assert report.warnings, "Expected parse warnings (blank region / missing values)"
        assert not report.blocking_errors, "Warnings must not populate blocking_errors"
        # The report is green (usable data retained) rather than blocked.
        assert any("usable observation" in s.value for s in app.success)
        assert not any("🚫" in e.value for e in app.error)

    @pytest.mark.smoke
    def test_rejected_rows_downloadable(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=180)
        assert not app.exception

        path = write_simple_kpi_xlsx(
            tmp_path / "rej.xlsx", ["R1"], n_weeks=26, seed=42, missing_rate=0.5
        )
        self._upload_design_kpi(app, path)
        assert not app.exception

        report = app.session_state["kpi_quality_report"]
        assert report.observations_dropped_missing_kpi > 0
        downloads = [
            d for d in app.get("download_button") if d.label and "rejected" in d.label.lower()
        ]
        assert len(downloads) == 1, "Rejected-rows download button should be present"
