"""The local serialisable experiment record (no database).

An :class:`ExperimentRecord` is the single audit/reproducibility object for one
workflow session: experiment identity, the current deterministic input
fingerprint, explicit per-stage statuses and result fingerprints, frozen design
versions, the latest analysed-period summary, and a chronological note log.
It serialises to/from plain JSON-safe dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geotestlab.experiment.identity import utc_now_iso
from geotestlab.experiment.stages import STAGE_KEYS, default_stage_status


@dataclass
class ExperimentRecord:
    """Typed, serialisable workflow record for one experiment session."""

    experiment_id: str
    created_at: str
    updated_at: str
    input_fingerprint: str = ""
    input_summary: dict = field(default_factory=dict)
    stage_status: dict = field(default_factory=default_stage_status)
    # stage -> fingerprint at which that stage's result was produced.
    stage_fingerprints: dict = field(default_factory=dict)
    # stage -> bool, computed staleness flags (result exists but inputs changed).
    stage_stale: dict = field(default_factory=dict)
    # Frozen approved design versions (list of FrozenVersion dicts, newest last).
    frozen_versions: list = field(default_factory=list)
    # Latest analysed-period summary (pre/test/post boundaries + counts).
    analysed: dict | None = None
    # Chronological human-readable note log.
    notes: list = field(default_factory=list)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """JSON-safe dict (all values are scalars / lists / dicts / None)."""
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_fingerprint": self.input_fingerprint,
            "input_summary": dict(self.input_summary),
            "stage_status": dict(self.stage_status),
            "stage_fingerprints": dict(self.stage_fingerprints),
            "stage_stale": dict(self.stage_stale),
            "frozen_versions": [dict(v) for v in self.frozen_versions],
            "analysed": dict(self.analysed) if self.analysed else None,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExperimentRecord:
        """Rebuild a record from a previously exported dict (tolerant of missing keys)."""
        return cls(
            experiment_id=str(data.get("experiment_id", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            input_fingerprint=str(data.get("input_fingerprint", "")),
            input_summary=dict(data.get("input_summary") or {}),
            stage_status=dict(data.get("stage_status") or default_stage_status()),
            stage_fingerprints=dict(data.get("stage_fingerprints") or {}),
            stage_stale=dict(data.get("stage_stale") or {}),
            frozen_versions=[dict(v) for v in (data.get("frozen_versions") or [])],
            analysed=dict(data.get("analysed")) if data.get("analysed") else None,
            notes=list(data.get("notes") or []),
        )


def create_experiment_record(now=None) -> ExperimentRecord:
    """Create a fresh record with a new experiment identity."""
    from geotestlab.experiment.identity import new_experiment_id

    stamp = utc_now_iso(now)
    return ExperimentRecord(
        experiment_id=new_experiment_id(now),
        created_at=stamp,
        updated_at=stamp,
        stage_status=default_stage_status(),
        stage_fingerprints={},
        stage_stale={},
        frozen_versions=[],
        analysed=None,
        notes=[f"Experiment created at {stamp}."],
    )


def touch(record: ExperimentRecord, now=None) -> None:
    """Update the record's updated_at timestamp in place."""
    record.updated_at = utc_now_iso(now)


def add_note(record: ExperimentRecord, message: str, now=None) -> None:
    """Append a timestamped note and bump updated_at in place."""
    record.notes.append(f"{utc_now_iso(now)} — {message}")
    touch(record, now)


def update_inputs(
    record: ExperimentRecord, fingerprint: str, input_summary: dict | None = None, now=None
) -> None:
    """Record the current workflow inputs (fingerprint + human summary)."""
    record.input_fingerprint = fingerprint
    if input_summary is not None:
        record.input_summary = dict(input_summary)
    touch(record, now)


def record_stage_result(
    record: ExperimentRecord, stage: str, fingerprint: str, status: str = "completed", now=None
) -> None:
    """Record that a stage produced a result under the given input fingerprint."""
    if stage not in STAGE_KEYS:
        raise ValueError(f"Unknown stage: {stage!r}")
    record.stage_fingerprints[stage] = fingerprint
    record.stage_status[stage] = status
    record.stage_stale[stage] = False
    touch(record, now)


def set_stage_status(record: ExperimentRecord, stage: str, status: str) -> None:
    """Explicitly set a stage's status (without touching result fingerprints)."""
    if stage not in STAGE_KEYS:
        raise ValueError(f"Unknown stage: {stage!r}")
    record.stage_status[stage] = status


def stage_has_result(record: ExperimentRecord, stage: str) -> bool:
    return stage in record.stage_fingerprints and bool(record.stage_fingerprints.get(stage))
