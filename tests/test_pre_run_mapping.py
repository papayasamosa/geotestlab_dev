"""Stage 1: pre-run region-mapping quality.

Covers:
- the pure region-mapping functions (``build_region_mapping``,
  ``compute_region_mapping_report``, ``uncovered_required_regions``,
  ``region_mapping_fingerprint`` and the report's ``covered_regions``);
- clean mapped input leaves the analytical data unchanged (pure parity);
- AppTest coverage: the mapping report appears before Run, a selected
  unmapped test region blocks Run, an unused unmapped raw region warns but
  does not block, and a mapping-relevant input change (metric) invalidates
  and recomputes the report. Geography invalidation is covered at the pure
  fingerprint level because changing the geography level resets matching
  state (``final_controls`` -> None), which makes the validation tab return
  early before the report can be rendered in AppTest.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from geotestlab.data.mapping import (
    build_region_mapping,
    compute_region_mapping_report,
    region_mapping_fingerprint,
    uncovered_required_regions,
)
from geotestlab.data.models import compute_mapping_report
from tests.fixtures.live_scenarios import (
    RUN_TIMEOUT,
    _manual_match,
    _pick_test_auto_match,
    _run_match,
    _upload_kpi,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _long_frame(rows) -> pd.DataFrame:
    """Build a minimal long-format KPI frame (region_raw, metric_name, date, kpi)."""
    return pd.DataFrame(
        rows,
        columns=["region_raw", "metric_name", "date", "kpi"],
    )


# ---------------------------------------------------------------------------
# build_region_mapping — pure
# ---------------------------------------------------------------------------


class TestBuildRegionMapping:
    def test_adobe_mapping_takes_precedence(self):
        df = _long_frame([("ADB_ABD", "Sales", pd.Timestamp("2026-01-04"), 1.0)])
        mapped = build_region_mapping(df.copy(), ["Aberdeen City"], {"ADB_ABD": "Aberdeen City"})
        assert mapped["region"].tolist() == ["Aberdeen City"]

    def test_direct_match_fallback(self):
        df = _long_frame([("Aberdeen City", "Sales", pd.Timestamp("2026-01-04"), 1.0)])
        mapped = build_region_mapping(df.copy(), ["Aberdeen City"], {})
        assert mapped["region"].tolist() == ["Aberdeen City"]

    def test_unmapped_label_becomes_none(self):
        df = _long_frame([("R1", "Sales", pd.Timestamp("2026-01-04"), 1.0)])
        mapped = build_region_mapping(df.copy(), ["Aberdeen City"], {})
        assert mapped["region"].isna().all()

    def test_valid_regions_must_be_full_universe_not_selected_only(self):
        """A raw label that is NOT among the selected regions still maps when it
        is part of the full candidate universe (direct-match fallback)."""
        df = _long_frame([("Angus", "Sales", pd.Timestamp("2026-01-04"), 1.0)])
        mapped = build_region_mapping(df.copy(), ["Aberdeen City", "Angus"], {})
        assert mapped["region"].tolist() == ["Angus"]


# ---------------------------------------------------------------------------
# compute_region_mapping_report — pure
# ---------------------------------------------------------------------------


class TestComputeRegionMappingReport:
    def test_metric_filtering_and_covered_regions(self):
        df = _long_frame(
            [
                ("A", "Sales", pd.Timestamp("2026-01-04"), 1.0),
                ("A", "Sales", pd.Timestamp("2026-01-11"), 2.0),
                ("B", "Sales", pd.Timestamp("2026-01-04"), 3.0),
                ("C", "Sales", pd.Timestamp("2026-01-04"), 4.0),
                ("A", "Visits", pd.Timestamp("2026-01-04"), 5.0),
            ]
        )
        report = compute_region_mapping_report(
            df, ["X", "Y", "Z"], {"A": "X", "B": "Y"}, metric_name="Sales"
        )
        assert report.raw_regions == ("A", "B", "C")
        assert report.mapped_regions == ("A", "B")
        assert report.unmapped_regions == ("C",)
        assert report.covered_regions == ("X", "Y")
        assert report.unmapped_rows is not None
        assert set(report.unmapped_rows["region_raw"]) == {"C"}

    def test_does_not_mutate_caller_frame(self):
        df = _long_frame([("A", "Sales", pd.Timestamp("2026-01-04"), 1.0)])
        columns_before = list(df.columns)
        compute_region_mapping_report(df, ["X"], {"A": "X"}, metric_name="Sales")
        assert list(df.columns) == columns_before
        assert "region" not in df.columns

    def test_without_metric_uses_all_rows(self):
        df = _long_frame(
            [
                ("A", "Sales", pd.Timestamp("2026-01-04"), 1.0),
                ("B", "Visits", pd.Timestamp("2026-01-04"), 2.0),
            ]
        )
        report = compute_region_mapping_report(df, ["X", "Y"], {"A": "X", "B": "Y"})
        assert report.raw_regions == ("A", "B")
        assert report.covered_regions == ("X", "Y")


class TestCoveredRegionsInReport:
    def test_compute_mapping_report_populates_covered_regions(self):
        df = pd.DataFrame(
            {
                "region_raw": ["A", "A", "B", "C"],
                "region": ["X", "X", "Y", None],
                "kpi": [1.0, 2.0, 3.0, 4.0],
            }
        )
        rep = compute_mapping_report(df)
        assert rep.covered_regions == ("X", "Y")

    def test_all_unmapped_has_empty_covered(self):
        df = pd.DataFrame({"region_raw": ["A"], "region": [None], "kpi": [1.0]})
        rep = compute_mapping_report(df)
        assert rep.covered_regions == ()
        assert rep.unmapped_regions == ("A",)


# ---------------------------------------------------------------------------
# uncovered_required_regions — pure blocking decision
# ---------------------------------------------------------------------------


class TestUncoveredRequiredRegions:
    @staticmethod
    def _report(covered=("X", "Y"), unmapped=("R1",)):
        return compute_mapping_report(
            pd.DataFrame(
                {
                    "region_raw": ["A", "B", "R1"],
                    "region": ["X", "Y", None],
                    "kpi": [1.0, 2.0, 3.0],
                }
            )
        )

    def test_uncovered_selected_region_blocks(self):
        rep = self._report(covered=("X", "Y"))
        assert uncovered_required_regions(rep, ["X", "Z"]) == ("Z",)

    def test_unused_unmapped_raw_region_does_not_block(self):
        rep = self._report(covered=("X", "Y"), unmapped=("R1",))
        assert uncovered_required_regions(rep, ["X"]) == ()
        # R1 is unmapped but unused — not a blocker.
        assert "R1" in rep.unmapped_regions
        assert uncovered_required_regions(rep, ["X", "Y"]) == ()

    def test_empty_required_never_blocks(self):
        rep = self._report()
        assert uncovered_required_regions(rep, []) == ()


# ---------------------------------------------------------------------------
# region_mapping_fingerprint — invalidation contract
# ---------------------------------------------------------------------------


class TestRegionMappingFingerprint:
    BASE = dict(
        file_name="kpi.xlsx",
        file_size=1234,
        market="UK",
        geo_col="Local Authority Area",
        selected_metric="Sales",
        agg_col=None,
        mapping_source="structural",
    )

    def test_any_mapping_input_change_invalidates(self):
        for key in (
            "file_name",
            "file_size",
            "market",
            "geo_col",
            "selected_metric",
            "agg_col",
            "mapping_source",
        ):
            altered = dict(self.BASE)
            altered[key] = "changed"
            assert region_mapping_fingerprint(**altered) != region_mapping_fingerprint(
                **self.BASE
            ), f"fingerprint did not change on {key}"

    def test_identical_inputs_give_identical_fingerprint(self):
        a = region_mapping_fingerprint(**self.BASE)
        b = region_mapping_fingerprint(**self.BASE)
        assert a == b


# ---------------------------------------------------------------------------
# Clean mapped input parity — pure
# ---------------------------------------------------------------------------


class TestCleanMappedInputParity:
    def test_clean_mapped_input_leaves_analytical_data_unchanged(self):
        """A fully-mapped file yields an all-mapped report and the caller's
        long-format data is not modified by the pre-run computation."""
        df = _long_frame(
            [
                ("Aberdeen City", "Sales", pd.Timestamp("2026-01-04"), 10.0),
                ("Angus", "Sales", pd.Timestamp("2026-01-04"), 20.0),
            ]
        )
        columns_before = list(df.columns)
        report = compute_region_mapping_report(
            df,
            ["Aberdeen City", "Angus"],
            {},
            metric_name="Sales",
        )
        assert report.unmapped_regions == ()
        assert report.covered_regions == ("Aberdeen City", "Angus")
        assert report.unmapped_rows is None
        assert list(df.columns) == columns_before


# ---------------------------------------------------------------------------
# Live AppTest coverage
# ---------------------------------------------------------------------------


class TestPreRunMappingUI:
    """The mapping report must appear before Run and gate modelling correctly."""

    @staticmethod
    def _new_app() -> AppTest:
        app = AppTest.from_file(str(REPO_ROOT / "geotestmatch.py"))
        app.run(timeout=RUN_TIMEOUT)
        return app

    @staticmethod
    def _uploaded(app: AppTest, path: Path) -> AppTest:
        _upload_kpi(app, "design", path.name, path.read_bytes())
        return app

    def test_mapping_report_appears_before_run(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = self._new_app()
        _pick_test_auto_match(app, "Aberdeen City")
        _run_match(app)

        path = write_simple_kpi_xlsx(tmp_path / "kpi.xlsx", ["R1", "R2"], n_weeks=26, seed=42)
        self._uploaded(app, path)

        assert not app.exception
        # Computed without any Run click.
        assert "kpi_mapping_report" in app.session_state
        report = app.session_state["kpi_mapping_report"]
        assert report is not None
        assert report.unmapped_regions == ("R1", "R2")
        assert report.unmapped_rows is not None
        assert "kpi_mapping_fingerprint" in app.session_state

        # Rendered inside the data-quality report before modelling.
        metric_labels = [m.label for m in app.metric]
        assert any("Raw regions" in label for label in metric_labels)
        assert any("Mapped regions" in label for label in metric_labels)
        assert any("Unmapped regions" in label for label in metric_labels)
        assert any("Unmapped regions: R1, R2" in w.value for w in app.warning)
        downloads = [
            d for d in app.get("download_button") if d.label and "unmapped" in d.label.lower()
        ]
        assert len(downloads) == 1, "Unmapped-rows download should be present pre-run"

    def test_selected_unmapped_test_region_blocks_run(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = self._new_app()
        _pick_test_auto_match(app, "Aberdeen City")
        _run_match(app)

        # Uploaded data does not cover the selected test region at all.
        path = write_simple_kpi_xlsx(tmp_path / "kpi.xlsx", ["R1", "R2"], n_weeks=26, seed=42)
        self._uploaded(app, path)

        assert not app.exception
        report = app.session_state["kpi_mapping_report"]
        assert report is not None
        assert "Aberdeen City" not in report.covered_regions

        run_btn = [b for b in app.button if b.key == "design_run_button"][0]
        run_btn.click()
        app.run(timeout=RUN_TIMEOUT)

        assert not app.exception
        assert any("no mapped data" in e.value for e in app.error)
        assert app.session_state["validation_triggered"] is False

    def test_unused_unmapped_raw_region_warns_but_does_not_block(self, tmp_path):
        from tests.fixture_factories.write_correlated_kpi_xlsx import write_correlated_kpi_xlsx

        app = self._new_app()
        _manual_match(app)  # test: Aberdeen City; controls: Aberdeenshire, Angus

        # Daily file (weekly is the default selection) -> a genuine unacknowledged
        # frequency mismatch, which is a CHEAP gate that fires AFTER the mapping
        # gate in the run path. A manually-triggered run therefore proves the
        # mapping gate passed without paying for a full validation run.
        path = write_correlated_kpi_xlsx(
            tmp_path / "daily.xlsx",
            "Aberdeen City",
            ["Aberdeenshire", "Angus", "R1"],
            n_periods=60,
            freq="D",
            seed=42,
        )
        self._uploaded(app, path)

        assert not app.exception
        report = app.session_state["kpi_mapping_report"]
        assert report is not None
        assert "R1" in report.unmapped_regions  # unused raw region unmapped
        assert "Aberdeen City" in report.covered_regions  # selected test covered

        # Warns, does not block.
        assert any("Unmapped regions: R1" in w.value for w in app.warning)
        assert not any("no mapped data" in e.value for e in app.error)

        # A triggered run passes the mapping gate and stops at the (cheap)
        # frequency-mismatch gate instead — i.e. not blocked by mapping.
        app.session_state["validation_triggered"] = True
        app.run(timeout=RUN_TIMEOUT)
        assert not app.exception
        assert not any("no mapped data" in e.value for e in app.error)
        assert any("unacknowledged frequency mismatch" in e.value for e in app.error)
        assert app.session_state["validation_triggered"] is False

    def test_changing_metric_invalidates_and_recomputes_mapping(self, tmp_path):
        """A mapping-relevant input change (selected metric) must invalidate and
        recompute the stored report via the fingerprint."""
        dates = pd.date_range("2026-01-04", periods=12, freq="W")
        rows: list[dict] = []
        for region in ["Aberdeen City", "Aberdeenshire"]:
            for metric in ["Sales", "Visits"]:
                row = {"Region": region, "Metric": metric}
                for i, d in enumerate(dates):
                    row[d] = float(100 + i)
                rows.append(row)
        # "R1" exists only under Visits, so the two metrics map differently.
        extra: dict = {"Region": "R1", "Metric": "Visits"}
        for i, d in enumerate(dates):
            extra[d] = float(50 + i)
        rows.append(extra)
        path = tmp_path / "two_metrics.xlsx"
        pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")

        app = self._new_app()
        _manual_match(app)
        self._uploaded(app, path)

        assert not app.exception
        fp_sales = app.session_state["kpi_mapping_fingerprint"]
        assert fp_sales["selected_metric"] == "Sales"
        report_sales = app.session_state["kpi_mapping_report"]
        assert report_sales is not None
        assert report_sales.unmapped_regions == ()
        assert "Aberdeen City" in report_sales.covered_regions

        kpi_select = [s for s in app.selectbox if s.key == "design_selected_metric"][0]
        kpi_select.set_value("Visits")
        app.run(timeout=RUN_TIMEOUT)

        assert not app.exception
        fp_visits = app.session_state["kpi_mapping_fingerprint"]
        report_visits = app.session_state["kpi_mapping_report"]
        assert fp_visits["selected_metric"] == "Visits"
        assert fp_visits != fp_sales
        assert report_visits is not None
        # Recomputed for the new metric: R1 (Visits-only) is now unmapped.
        assert report_visits.unmapped_regions == ("R1",)
        assert "Aberdeen City" in report_visits.covered_regions

    def test_display_only_change_does_not_recompute_mapping(self, tmp_path):
        """Changing a display-only setting (time-series frequency) must not
        invalidate or recompute the mapping report."""
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = self._new_app()
        _pick_test_auto_match(app, "Aberdeen City")
        _run_match(app)

        # 52 weeks so the daily-mode validation sliders stay valid (min < max)
        # when the frequency radio is toggled.
        path = write_simple_kpi_xlsx(
            tmp_path / "kpi.xlsx",
            ["Aberdeen City", "Aberdeenshire", "Angus", "R1"],
            n_weeks=52,
            seed=42,
        )
        self._uploaded(app, path)

        assert not app.exception
        fp_before = app.session_state["kpi_mapping_fingerprint"]
        report_before = app.session_state["kpi_mapping_report"]

        freq_radio = [r for r in app.radio if r.key == "design_time_series_frequency"][0]
        freq_radio.set_value("daily")
        app.run(timeout=RUN_TIMEOUT)

        assert not app.exception
        assert app.session_state["kpi_mapping_fingerprint"] == fp_before
        assert app.session_state["kpi_mapping_report"] is report_before

    def test_clean_mapped_input_produces_unchanged_analytical_data(self, tmp_path):
        from tests.fixture_factories.write_simple_kpi_xlsx import write_simple_kpi_xlsx

        app = self._new_app()
        _manual_match(app)

        path = write_simple_kpi_xlsx(
            tmp_path / "kpi.xlsx",
            ["Aberdeen City", "Aberdeenshire", "Angus"],
            n_weeks=26,
            seed=42,
        )
        self._uploaded(app, path)

        assert not app.exception
        report = app.session_state["kpi_mapping_report"]
        assert report is not None
        assert report.unmapped_regions == ()
        assert report.unmapped_rows is None
        assert "Aberdeen City" in report.covered_regions
        # No unmapped warning and no blocker.
        assert not any("Unmapped regions:" in w.value for w in app.warning)
        assert not any("no mapped data" in e.value for e in app.error)
        run_btn = [b for b in app.button if b.key == "design_run_button"][0]
        assert run_btn.disabled is False
