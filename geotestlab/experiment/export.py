"""Reproducible experiment export (local serialisable record).

Exports carry an explicit schema version. ``load_experiment_record_from_export``
reconstructs a record from a v1 or v2 export, preserving the ability to load
existing v1 JSON exports. Frozen versions are deep-copied on export so mutating
an export dict never mutates the record's approved history.
"""

from __future__ import annotations

import copy

from geotestlab.experiment.freeze import FrozenVersion, planned_vs_analysed
from geotestlab.experiment.records import ExperimentRecord
from geotestlab.experiment.stages import STAGE_KEYS, stage_label

EXPORT_SCHEMA_VERSION = "experiment-record/v2"


def build_experiment_export(record: ExperimentRecord, result_summaries=None) -> dict:
    """Build a reproducible, JSON-safe export of the whole experiment record.

    ``result_summaries`` is an optional dict of serialisable result summaries
    keyed by stage (e.g. validation summary dicts), included verbatim so the
    export is self-contained. Content digests and stage-method results are
    included; raw sensitive values are never included.
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
        "schema_version": EXPORT_SCHEMA_VERSION,
        "experiment_id": record.experiment_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "record_schema_version": record.schema_version,
        "input_fingerprint": record.input_fingerprint,
        "input_summary": dict(record.input_summary or {}),
        "stages": stages,
        "frozen_versions": [v.to_dict() for v in (record.frozen_versions or [])],
        "planned_vs_analysed": comparison,
        "analysed": copy.deepcopy(dict(record.analysed)) if record.analysed else None,
        "content_digests": copy.deepcopy(dict(record.content_digests or {})),
        "stage_method_results": copy.deepcopy(
            {str(k): dict(v) for k, v in (record.stage_method_results or {}).items()}
        ),
        "notes": list(record.notes or []),
        "result_summaries": dict(result_summaries) if result_summaries else {},
    }
    return export


def load_experiment_record_from_export(data: dict) -> ExperimentRecord:
    """Reconstruct an :class:`ExperimentRecord` from a v1 or v2 export dict.

    v1 exports lack ``record_schema_version``, ``content_digests`` and
    ``stage_method_results``, and store stage statuses in a ``stages`` list;
    all of these load with defaults while preserving stage statuses,
    fingerprints, staleness and frozen versions.
    """
    stages = data.get("stages") or []
    stage_status = {str(s.get("key")): str(s.get("status", "not_started")) for s in stages}
    stage_fingerprints = {
        str(s.get("key")): str(s.get("result_fingerprint"))
        for s in stages
        if s.get("result_fingerprint")
    }
    stage_stale = {str(s.get("key")): bool(s.get("stale", False)) for s in stages}
    return ExperimentRecord(
        experiment_id=str(data.get("experiment_id", "")),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        schema_version=str(data.get("record_schema_version", "experiment-record/v1")),
        input_fingerprint=str(data.get("input_fingerprint", "")),
        input_summary=dict(data.get("input_summary") or {}),
        stage_status=stage_status,
        stage_fingerprints=stage_fingerprints,
        stage_stale=stage_stale,
        frozen_versions=[FrozenVersion.from_dict(v) for v in (data.get("frozen_versions") or [])],
        analysed=copy.deepcopy(dict(data.get("analysed"))) if data.get("analysed") else None,
        content_digests=dict(data.get("content_digests") or {}),
        stage_method_results={
            str(k): dict(v) for k, v in (data.get("stage_method_results") or {}).items()
        },
        notes=list(data.get("notes") or []),
    )
