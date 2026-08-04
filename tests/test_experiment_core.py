"""Direct deterministic unit tests for the experiment core (Stage 4).

Covers, with small hand-calculable fixtures (no Streamlit):
- experiment identity (id format, UTC timestamps);
- deterministic input fingerprints (ordering-insensitive, value-tolerant);
- explicit stage statuses (defaults: future stages planned);
- serialisable experiment records (round-trip, stage result stamps);
- stale-result propagation;
- frozen approved design versions (freeze, version history, active version);
- planned-versus-analysed comparison;
- reproducible experiment export (JSON-safe).
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from geotestlab.experiment import (
    STAGE_KEYS,
    ExperimentRecord,
    active_frozen_version,
    analytical_data_digest,
    build_content_digests,
    build_experiment_export,
    candidate_universe_digest,
    compute_input_fingerprint,
    create_experiment_record,
    default_stage_status,
    freeze_design,
    is_frozen,
    load_experiment_record,
    load_experiment_record_from_export,
    new_experiment_id,
    planned_vs_analysed,
    propagate_staleness,
    record_stage_method_result,
    record_stage_result,
    sha256_bytes,
    stage_is_stale,
    update_inputs,
    utc_now_iso,
)

NOW = datetime(2026, 8, 4, 10, 30, 0)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
class TestIdentity:
    def test_id_format(self):
        rid = new_experiment_id(NOW)
        assert rid.startswith("EXP-20260804-")
        assert len(rid) == len("EXP-20260804-XXXX")

    def test_ids_unique(self):
        a = new_experiment_id(NOW)
        b = new_experiment_id(NOW)
        assert a != b

    def test_utc_now_iso(self):
        assert utc_now_iso(NOW) == "2026-08-04T10:30:00Z"
        # Naive datetimes are treated as UTC.
        assert utc_now_iso(datetime(2026, 1, 1, 0, 0, 0)) == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Deterministic fingerprints
# ---------------------------------------------------------------------------
class TestFingerprints:
    def test_deterministic_same_inputs(self):
        a = {"market": "UK", "regions": ["A", "B"], "weights": {"x": 1.5}}
        b = {"weights": {"x": 1.5}, "regions": ["A", "B"], "market": "UK"}
        assert compute_input_fingerprint(a) == compute_input_fingerprint(b)

    def test_different_inputs_differ(self):
        a = {"market": "UK"}
        b = {"market": "US"}
        assert compute_input_fingerprint(a) != compute_input_fingerprint(b)

    def test_numpy_and_timestamp_values(self):
        fp = compute_input_fingerprint(
            {
                "array": np.array([1.0, 2.0, 3.0]),
                "ts": pd.Timestamp("2026-08-04"),
                "nested": {"a": np.int64(5), "b": [pd.Timestamp("2026-01-01"), None]},
                "nan": float("nan"),
            }
        )
        assert isinstance(fp, str) and fp.startswith("fp1:")
        # Same values with plain python types produce the same fingerprint.
        fp_plain = compute_input_fingerprint(
            {
                "array": [1.0, 2.0, 3.0],
                "ts": "2026-08-04T00:00:00",
                "nested": {"a": 5, "b": ["2026-01-01T00:00:00", None]},
                "nan": "NaN",
            }
        )
        assert fp == fp_plain

    def test_json_serialisable(self):
        out = compute_input_fingerprint({"regions": ["A", "B"], "n": np.int64(3)})
        assert len(out) > len("fp1:")


# ---------------------------------------------------------------------------
# Stage statuses
# ---------------------------------------------------------------------------
class TestStages:
    def test_default_statuses(self):
        status = default_stage_status()
        assert set(status) == set(STAGE_KEYS)
        assert status["match_quality"] == "not_started"
        assert status["counterfactual_validation"] == "not_started"
        assert status["statistical_power"] == "planned"
        assert status["media_delivery"] == "planned"
        assert status["effect_plausibility"] == "planned"
        assert status["observed_impact"] == "not_started"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
class TestRecords:
    def test_create_and_round_trip(self):
        rec = create_experiment_record(NOW)
        assert rec.experiment_id.startswith("EXP-")
        assert rec.created_at == "2026-08-04T10:30:00Z"
        assert rec.updated_at == rec.created_at
        assert rec.frozen_versions == []
        assert rec.notes

        d = rec.to_dict()
        assert json.dumps(d)  # JSON-safe
        rec2 = ExperimentRecord.from_dict(d)
        assert rec2.experiment_id == rec.experiment_id
        assert rec2.stage_status == rec.stage_status
        assert rec2.input_fingerprint == rec.input_fingerprint

    def test_record_stage_result_stamps_fingerprint(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        record_stage_result(rec, "match_quality", fp)
        assert rec.stage_status["match_quality"] == "completed"
        assert rec.stage_fingerprints["match_quality"] == fp
        assert rec.stage_stale["match_quality"] is False

    def test_unknown_stage_rejected(self):
        rec = create_experiment_record(NOW)
        with pytest.raises(ValueError):
            record_stage_result(rec, "bogus", "fp1:x")

    def test_update_inputs(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"market": "UK"})
        update_inputs(rec, fp, {"market": "UK"})
        assert rec.input_fingerprint == fp
        assert rec.input_summary == {"market": "UK"}


# ---------------------------------------------------------------------------
# Stale-result propagation
# ---------------------------------------------------------------------------
class TestStale:
    def test_no_result_not_stale(self):
        rec = create_experiment_record(NOW)
        assert stage_is_stale(rec, "match_quality", "fp1:anything") is False

    def test_same_fingerprint_not_stale(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        record_stage_result(rec, "match_quality", fp)
        assert stage_is_stale(rec, "match_quality", fp) is False

    def test_changed_fingerprint_stale(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        record_stage_result(rec, "match_quality", fp1)
        assert stage_is_stale(rec, "match_quality", fp2) is True

    def test_propagate_marks_stale_and_reports(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        record_stage_result(rec, "match_quality", fp1)
        record_stage_result(rec, "counterfactual_validation", fp1)
        changed = propagate_staleness(rec, fp2)
        assert set(changed) == {"match_quality", "counterfactual_validation"}
        assert rec.stage_status["match_quality"] == "stale"
        assert rec.stage_stale["match_quality"] is True
        # Planned stages never become stale.
        assert rec.stage_status["statistical_power"] == "planned"

    def test_propagate_clears_stale_when_current(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        record_stage_result(rec, "match_quality", fp1)
        propagate_staleness(rec, fp2)
        assert rec.stage_status["match_quality"] == "stale"
        # Re-stamp under the new fingerprint and re-propagate -> current again.
        record_stage_result(rec, "match_quality", fp2)
        propagate_staleness(rec, fp2)
        assert rec.stage_status["match_quality"] == "completed"
        assert rec.stage_stale["match_quality"] is False


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------
class TestFreeze:
    def _planned(self, **over):
        base = {
            "pre_start": "2025-01-06",
            "pre_end": "2025-03-24",
            "test_start": "2025-03-31",
            "test_end": "2025-04-21",
            "use_post": False,
            "post_start": None,
            "post_end": None,
            "time_series_frequency": "weekly",
            "planned_test_periods": 4,
            "analysed_test_periods": 4,
            "excluded_test_periods": 0,
        }
        base.update(over)
        return base

    def test_freeze_appends_version(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        assert is_frozen(rec) is False
        frozen = freeze_design(rec, self._planned(), fp, label="v1")
        assert frozen["version"] == 1
        assert is_frozen(rec) is True
        assert active_frozen_version(rec)["version"] == 1
        freeze_design(rec, self._planned(), fp, label="v2")
        assert len(rec.frozen_versions) == 2
        assert active_frozen_version(rec)["version"] == 2

    def test_planned_vs_analysed_no_freeze(self):
        rec = create_experiment_record(NOW)
        cmp = planned_vs_analysed(rec)
        assert cmp["frozen"] is False
        assert cmp["matches"] is False
        assert cmp["differences"]

    def test_planned_vs_analysed_match(self):
        rec = create_experiment_record(NOW)
        planned = self._planned()
        fp = compute_input_fingerprint({"a": 1})
        update_inputs(rec, fp)
        freeze_design(rec, planned, fp)
        rec.analysed = dict(planned)  # analysed identical to planned
        cmp = planned_vs_analysed(rec)
        assert cmp["frozen"] is True
        assert cmp["matches"] is True
        assert cmp["differences"] == []
        assert cmp["design_changed_since_freeze"] is False

    def test_planned_vs_analysed_mismatch(self):
        rec = create_experiment_record(NOW)
        planned = self._planned()
        fp = compute_input_fingerprint({"a": 1})
        update_inputs(rec, fp)
        freeze_design(rec, planned, fp)
        analysed = dict(planned)
        analysed["analysed_test_periods"] = 3
        analysed["excluded_test_periods"] = 1
        rec.analysed = analysed
        cmp = planned_vs_analysed(rec)
        assert cmp["matches"] is False
        assert cmp["analysed_counts"]["analysed_test_periods"] == 3
        assert any("analysed test period count" in d for d in cmp["differences"])

    def test_design_changed_since_freeze(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        freeze_design(rec, self._planned(), fp1)
        update_inputs(rec, fp2)
        cmp = planned_vs_analysed(rec)
        assert cmp["design_changed_since_freeze"] is True


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
class TestExport:
    def test_export_is_json_safe_and_complete(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"market": "UK", "n": np.int64(3)})
        update_inputs(rec, fp, {"market": "UK"})
        record_stage_result(rec, "match_quality", fp)
        planned = {
            "pre_start": "2025-01-06",
            "test_start": "2025-03-31",
            "test_end": "2025-04-21",
            "planned_test_periods": 4,
            "analysed_test_periods": 4,
            "excluded_test_periods": 0,
        }
        freeze_design(rec, planned, fp)
        rec.analysed = dict(planned)
        export = build_experiment_export(rec, result_summaries={"match_quality": {"corr": 0.9}})
        assert export["schema_version"] == "experiment-record/v2"
        assert export["record_schema_version"] == "experiment-record/v2"
        assert export["content_digests"] == {}
        assert export["stage_method_results"] == {}
        assert export["frozen_versions"][0]["schema_version"] == "frozen-design/v1"
        assert export["experiment_id"] == rec.experiment_id
        assert export["input_fingerprint"] == fp
        assert len(export["stages"]) == len(STAGE_KEYS)
        stages = {s["key"]: s for s in export["stages"]}
        assert stages["match_quality"]["status"] == "completed"
        assert stages["match_quality"]["stale"] is False
        assert stages["statistical_power"]["status"] == "planned"
        assert export["frozen_versions"][0]["version"] == 1
        assert export["planned_vs_analysed"]["matches"] is True
        assert export["result_summaries"]["match_quality"] == {"corr": 0.9}
        # Fully JSON-serialisable.
        json.dumps(export)

    def test_export_stale_status(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        record_stage_result(rec, "match_quality", fp1)
        propagate_staleness(rec, fp2)
        export = build_experiment_export(rec)
        stage = next(s for s in export["stages"] if s["key"] == "match_quality")
        assert stage["status"] == "stale"
        assert stage["stale"] is True


# ---------------------------------------------------------------------------
# Content digests (Stage 2: SHA-256 identities, digests only)
# ---------------------------------------------------------------------------
class TestContentDigests:
    def test_bytes_digest_deterministic(self):
        assert sha256_bytes(b"hello") == sha256_bytes(b"hello")
        assert sha256_bytes(b"hello").startswith("sha256:")
        assert sha256_bytes(b"world") != sha256_bytes(b"hello")

    def test_frame_digest_row_order_independent(self):
        df = pd.DataFrame(
            {
                "date": ["2025-01-06", "2025-01-13"],
                "region": ["T", "C1"],
                "kpi": [1.0, 2.0],
            }
        )
        shuffled = df.iloc[[1, 0]].reset_index(drop=True)
        assert analytical_data_digest(df) == analytical_data_digest(shuffled)

    def test_universe_digest_sorted_deduped(self):
        assert candidate_universe_digest(["B", "A", "B"]) == candidate_universe_digest(["A", "B"])

    def test_build_content_digests_json_safe_and_digests_only(self):
        out = build_content_digests(
            source_bytes=b"RAW-SOURCE-BYTES",
            analytical_data=pd.DataFrame({"x": [1, 2]}),
            workbook_bytes=b"RAW-WORKBOOK-BYTES",
            market_sheet=pd.DataFrame({"region": ["A"]}),
            candidate_universe=["A", "B"],
        )
        json.dumps(out)  # JSON-safe
        joined = json.dumps(out)
        assert "RAW-SOURCE-BYTES" not in joined
        assert "RAW-WORKBOOK-BYTES" not in joined
        for key in (
            "source_bytes",
            "analytical_data",
            "geography_workbook",
            "market_sheet",
            "candidate_universe",
        ):
            assert out[key].startswith("sha256:")

    def test_missing_content_reports_none(self):
        out = build_content_digests()
        assert out["source_bytes"] is None
        assert out["analytical_data"] is None
        assert out["geography_workbook"] is None
        assert out["market_sheet"] is None
        assert out["candidate_universe"] is None


# ---------------------------------------------------------------------------
# Restore completed status (completed -> change -> stale -> original -> completed)
# ---------------------------------------------------------------------------
class TestRestoreCompleted:
    def test_completed_change_stale_restore_completed(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        record_stage_result(rec, "match_quality", fp1)
        record_stage_result(rec, "counterfactual_validation", fp1)

        # inputs change -> stale
        changed = propagate_staleness(rec, fp2)
        assert set(changed) == {"match_quality", "counterfactual_validation"}
        assert rec.stage_status["match_quality"] == "stale"
        assert rec.stage_stale["match_quality"] is True

        # original inputs restored -> completed restored WITHOUT re-running
        changed2 = propagate_staleness(rec, fp1)
        assert "match_quality" in changed2
        assert rec.stage_status["match_quality"] == "completed"
        assert rec.stage_stale["match_quality"] is False
        assert rec.stage_status["counterfactual_validation"] == "completed"

    def test_stage_without_result_never_restored(self):
        rec = create_experiment_record(NOW)
        fp1 = compute_input_fingerprint({"a": 1})
        fp2 = compute_input_fingerprint({"a": 2})
        # no result -> not stale, stays not_started
        propagate_staleness(rec, fp2)
        assert rec.stage_status["match_quality"] == "not_started"
        propagate_staleness(rec, fp1)
        assert rec.stage_status["match_quality"] == "not_started"


# ---------------------------------------------------------------------------
# Immutable frozen versions (deep copies on store/return/export)
# ---------------------------------------------------------------------------
class TestFrozenImmutability:
    def _setup(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        return rec, fp

    def test_input_mutation_after_freeze_does_not_affect_stored(self):
        rec, fp = self._setup()
        planned = {"test_start": "2025-03-31", "planned_test_periods": 4}
        design = {"test_regions": ["T"], "weights": {"x": 1.0}}
        freeze_design(rec, planned, fp, design=design)
        planned["planned_test_periods"] = 999
        design["test_regions"].append("HACKED")
        stored = rec.frozen_versions[0]
        assert stored.planned["planned_test_periods"] == 4
        assert stored.design["test_regions"] == ["T"]

    def test_returned_frozen_dict_mutation_does_not_affect_stored(self):
        rec, fp = self._setup()
        frozen = freeze_design(rec, {"planned_test_periods": 4}, fp, design={"weights": {}})
        frozen["planned"]["planned_test_periods"] = 999
        frozen["design"]["weights"]["x"] = 9.0
        stored = rec.frozen_versions[0]
        assert stored.planned["planned_test_periods"] == 4
        assert stored.design["weights"] == {}

    def test_active_frozen_version_mutation_does_not_affect_stored(self):
        rec, fp = self._setup()
        freeze_design(rec, {"planned_test_periods": 4}, fp)
        active = active_frozen_version(rec)
        active["planned"]["planned_test_periods"] = 999
        assert rec.frozen_versions[0].planned["planned_test_periods"] == 4

    def test_export_dict_mutation_does_not_affect_record(self):
        rec, fp = self._setup()
        freeze_design(rec, {"planned_test_periods": 4}, fp, design={"weights": {"x": 1.0}})
        export = build_experiment_export(rec)
        export["frozen_versions"][0]["planned"]["planned_test_periods"] = 999
        export["frozen_versions"][0]["design"]["weights"]["x"] = 9.0
        assert rec.frozen_versions[0].planned["planned_test_periods"] == 4
        assert rec.frozen_versions[0].design["weights"] == {"x": 1.0}

    def test_record_mutation_after_export_does_not_affect_export(self):
        rec, fp = self._setup()
        freeze_design(rec, {"planned_test_periods": 4}, fp, design={"weights": {"x": 1.0}})
        export = build_experiment_export(rec)
        rec.frozen_versions[0].planned["planned_test_periods"] = 999
        rec.frozen_versions[0].design["weights"]["x"] = 9.0
        assert export["frozen_versions"][0]["planned"]["planned_test_periods"] == 4
        assert export["frozen_versions"][0]["design"]["weights"] == {"x": 1.0}


# ---------------------------------------------------------------------------
# Complete frozen snapshot (not just fingerprint + period dict)
# ---------------------------------------------------------------------------
class TestCompleteSnapshot:
    def test_freeze_stores_complete_design_snapshot(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        design = {
            "test_regions": ["T1", "T2"],
            "control_regions": ["C1"],
            "exclusions": ["2025-02-03"],
            "kpi": {
                "file_name": "weekly.xlsx",
                "selected_metric": "Sales",
                "time_series_frequency": "weekly",
            },
            "historical_period": {"pre_start": "2025-01-06", "pre_end": "2025-03-24"},
            "planned_test_period": {
                "test_start": "2025-03-31",
                "test_end": "2025-04-21",
                "planned_test_periods": 4,
            },
            "matching": {"method": "guided", "strategy": "deterministic", "weights": {"w1": 0.5}},
            "seeds": {"matching_seed": 42},
            "validation_settings": {"include_lagged_controls": True},
            "data_quality_summary": {"covered_regions": ["T1", "T2"], "rejected_rows": 0},
            "source_data_digests": {"source_bytes": "sha256:abc"},
            "tracking_outage_exclusions": ["2025-02-10"],
            "tool_version": "0.3.0",
            "methodology_version": "0.2.0",
            "analyst": {"label": "owner", "notes": ["approved"]},
            "approved_power_result": None,
        }
        frozen = freeze_design(rec, {"planned_test_periods": 4}, fp, label="v1", design=design)
        assert frozen["design"]["test_regions"] == ["T1", "T2"]
        assert frozen["design"]["tool_version"] == "0.3.0"
        assert frozen["design"]["methodology_version"] == "0.2.0"
        assert frozen["design"]["source_data_digests"] == {"source_bytes": "sha256:abc"}
        assert frozen["schema_version"] == "frozen-design/v1"
        assert frozen["planned"]["planned_test_periods"] == 4
        # deep-copied: mutating the caller's design dict never affects stored history
        design["test_regions"].append("HACKED")
        assert rec.frozen_versions[0].design["test_regions"] == ["T1", "T2"]


# ---------------------------------------------------------------------------
# Observed impact status (no Bayesian requirement; TBR as additional method)
# ---------------------------------------------------------------------------
class TestObservedImpact:
    def test_observed_impact_complete_without_bayesian(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        record_stage_result(rec, "counterfactual_validation", fp)
        record_stage_result(rec, "observed_impact", fp)
        assert rec.stage_status["observed_impact"] == "completed"
        assert rec.stage_fingerprints["observed_impact"] == fp
        assert rec.stage_stale["observed_impact"] is False

    def test_bayesian_tbr_stored_as_additional_method_result(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        fp_bayes = compute_input_fingerprint({"a": 1, "method": "bayesian"})
        record_stage_result(rec, "observed_impact", fp)
        record_stage_method_result(rec, "observed_impact", "bayesian_tbr", fp_bayes)
        assert rec.stage_fingerprints["observed_impact"] == fp  # primary unchanged
        assert rec.stage_method_results["observed_impact"] == {"bayesian_tbr": fp_bayes}
        assert rec.stage_status["observed_impact"] == "completed"
        assert rec.stage_stale["observed_impact"] is False

    def test_bayesian_tbr_completes_stage_if_no_primary(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"method": "bayesian"})
        record_stage_method_result(rec, "observed_impact", "bayesian_tbr", fp)
        assert rec.stage_status["observed_impact"] == "completed"
        assert rec.stage_fingerprints["observed_impact"] == fp

    def test_unknown_stage_rejected(self):
        rec = create_experiment_record(NOW)
        with pytest.raises(ValueError):
            record_stage_method_result(rec, "bogus", "bayesian_tbr", "fp1:x")


# ---------------------------------------------------------------------------
# Schema versioning and migration (v1 -> v2)
# ---------------------------------------------------------------------------
class TestVersioning:
    def test_v1_record_dict_loads_with_defaults(self):
        v1 = {
            "experiment_id": "EXP-20260804-ABCD",
            "created_at": "2026-08-04T10:30:00Z",
            "updated_at": "2026-08-04T10:30:00Z",
            "input_fingerprint": "fp1:abc",
            "stage_status": {"match_quality": "completed", "observed_impact": "completed"},
            "stage_fingerprints": {"match_quality": "fp1:abc"},
            "stage_stale": {},
            "frozen_versions": [
                {
                    "version": 1,
                    "frozen_at": "2026-08-04T10:30:00Z",
                    "input_fingerprint": "fp1:abc",
                    "label": "",
                    "planned": {"planned_test_periods": 4},
                }
            ],
            "analysed": {"planned_test_periods": 4},
            "notes": [],
        }
        rec = load_experiment_record(v1)
        assert rec.schema_version == "experiment-record/v1"
        assert rec.content_digests == {}
        assert rec.stage_method_results == {}
        assert rec.stage_status["match_quality"] == "completed"
        assert rec.frozen_versions[0].design == {}
        assert rec.frozen_versions[0].schema_version == "frozen-design/v1"
        assert rec.frozen_versions[0].planned["planned_test_periods"] == 4

    def test_round_trip_preserves_v2(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        rec.content_digests = {"source_bytes": "sha256:abc"}
        record_stage_result(rec, "observed_impact", fp)
        record_stage_method_result(rec, "observed_impact", "bayesian_tbr", fp)
        freeze_design(rec, {"planned_test_periods": 4}, fp, design={"test_regions": ["T"]})
        rec2 = load_experiment_record(rec.to_dict())
        assert rec2.schema_version == "experiment-record/v2"
        assert rec2.content_digests == {"source_bytes": "sha256:abc"}
        assert rec2.stage_method_results["observed_impact"] == {"bayesian_tbr": fp}
        assert rec2.frozen_versions[0].design == {"test_regions": ["T"]}
        assert rec2.to_dict() == rec.to_dict()

    def test_v1_export_loads(self):
        v1_export = {
            "schema_version": "experiment-record/v1",
            "experiment_id": "EXP-20260804-ABCD",
            "created_at": "2026-08-04T10:30:00Z",
            "updated_at": "2026-08-04T10:30:00Z",
            "input_fingerprint": "fp1:abc",
            "input_summary": {},
            "stages": [
                {
                    "key": "match_quality",
                    "label": "Match quality",
                    "status": "completed",
                    "stale": False,
                    "result_fingerprint": "fp1:abc",
                },
                {
                    "key": "counterfactual_validation",
                    "label": "Counterfactual validation",
                    "status": "not_started",
                    "stale": False,
                    "result_fingerprint": None,
                },
                {
                    "key": "observed_impact",
                    "label": "Observed impact",
                    "status": "completed",
                    "stale": True,
                    "result_fingerprint": "fp1:abc",
                },
                {
                    "key": "statistical_power",
                    "label": "Statistical power",
                    "status": "planned",
                    "stale": False,
                    "result_fingerprint": None,
                },
                {
                    "key": "media_delivery",
                    "label": "Media delivery",
                    "status": "planned",
                    "stale": False,
                    "result_fingerprint": None,
                },
                {
                    "key": "effect_plausibility",
                    "label": "Effect plausibility",
                    "status": "planned",
                    "stale": False,
                    "result_fingerprint": None,
                },
            ],
            "frozen_versions": [
                {
                    "version": 1,
                    "frozen_at": "2026-08-04T10:30:00Z",
                    "input_fingerprint": "fp1:abc",
                    "label": "",
                    "planned": {"planned_test_periods": 4},
                }
            ],
            "planned_vs_analysed": {},
            "analysed": {"planned_test_periods": 4},
            "notes": [],
            "result_summaries": {"match_quality": {"corr": 0.9}},
        }
        rec = load_experiment_record_from_export(v1_export)
        assert rec.schema_version == "experiment-record/v1"
        assert rec.stage_status["match_quality"] == "completed"
        assert rec.stage_status["observed_impact"] == "completed"
        assert rec.stage_stale["observed_impact"] is True
        assert rec.stage_fingerprints["observed_impact"] == "fp1:abc"
        assert rec.frozen_versions[0].planned["planned_test_periods"] == 4
        assert rec.content_digests == {}

    def test_v2_export_round_trip(self):
        rec = create_experiment_record(NOW)
        fp = compute_input_fingerprint({"a": 1})
        record_stage_result(rec, "match_quality", fp)
        freeze_design(rec, {"planned_test_periods": 4}, fp)
        export = build_experiment_export(rec)
        rec2 = load_experiment_record_from_export(export)
        assert rec2.experiment_id == rec.experiment_id
        assert rec2.stage_status == rec.stage_status
        assert rec2.schema_version == "experiment-record/v2"
        assert rec2.frozen_versions[0].planned["planned_test_periods"] == 4
