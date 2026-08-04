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
    build_experiment_export,
    compute_input_fingerprint,
    create_experiment_record,
    default_stage_status,
    freeze_design,
    is_frozen,
    new_experiment_id,
    planned_vs_analysed,
    propagate_staleness,
    record_stage_result,
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
        assert export["schema_version"] == "experiment-record/v1"
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
