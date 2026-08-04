"""Reproducible experiment export (local serialisable record)."""

from __future__ import annotations

from geotestlab.experiment.freeze import planned_vs_analysed
from geotestlab.experiment.records import ExperimentRecord
from geotestlab.experiment.stages import STAGE_KEYS, stage_label


def build_experiment_export(record: ExperimentRecord, result_summaries=None) -> dict:
    """Build a reproducible, JSON-safe export of the whole experiment record.

    ``result_summaries`` is an optional dict of serialisable result summaries
    keyed by stage (e.g. validation summary dicts), included verbatim so the
    export is self-contained.
    """
    comparison = planned_vs_analysed(record)
    stages = []
    for key in STAGE_KEYS:
        stages.append(
            {
                "key": key,
                "label": stage_label(key),
                "status": record.stage_status.get(key, "not_started"),
                "stale": bool(record.stage_stale.get(key, False)),
                "result_fingerprint": record.stage_fingerprints.get(key),
            }
        )
    export = {
        "schema_version": "experiment-record/v1",
        "experiment_id": record.experiment_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "input_fingerprint": record.input_fingerprint,
        "input_summary": dict(record.input_summary or {}),
        "stages": stages,
        "frozen_versions": [dict(v) for v in (record.frozen_versions or [])],
        "planned_vs_analysed": comparison,
        "analysed": dict(record.analysed) if record.analysed else None,
        "notes": list(record.notes or []),
        "result_summaries": dict(result_summaries) if result_summaries else {},
    }
    return export
