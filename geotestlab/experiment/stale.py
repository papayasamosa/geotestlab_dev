"""Stale-result propagation for the experiment record.

A stage's result is stale when the current workflow input fingerprint differs
from the fingerprint the result was produced under. The app already clears
stale result data; this module makes the staleness explicit in the record and
reports it so the UI can surface it.
"""

from __future__ import annotations

from geotestlab.experiment.records import ExperimentRecord, stage_has_result
from geotestlab.experiment.stages import STAGE_KEYS


def stage_is_stale(record: ExperimentRecord, stage: str, current_fingerprint: str) -> bool:
    """True if the stage has a result produced under a different fingerprint."""
    if not stage_has_result(record, stage):
        return False
    stored = record.stage_fingerprints.get(stage)
    return stored is not None and stored != current_fingerprint


def _current_for(current, stage: str) -> str:
    """Resolve a stage's current fingerprint from a string or {stage: fp} dict."""
    if isinstance(current, dict):
        return str(current.get(stage, "") or "")
    return str(current or "")


def compute_stale_flags(record: ExperimentRecord, current) -> dict:
    """Return {stage: bool} staleness flags for every workflow stage.

    ``current`` may be a single fingerprint string or a {stage: fingerprint}
    dict for stage-scoped comparison (empty per-stage fingerprints are treated
    as "no current result").
    """
    return {
        stage: stage_is_stale(record, stage, _current_for(current, stage)) for stage in STAGE_KEYS
    }


def propagate_staleness(record: ExperimentRecord, current) -> list:
    """Mark newly-stale completed stages as ``stale`` in the record.

    ``current`` may be a single fingerprint string or a {stage: fingerprint}
    dict for stage-scoped comparison (a stage with no current fingerprint is
    skipped here). Returns the list of stage keys whose status changed to
    ``stale`` (or that were already stale). Planned/future stages are never
    marked stale.
    """
    changed = []
    for stage in STAGE_KEYS:
        current_fingerprint = _current_for(current, stage)
        if not current_fingerprint:
            continue
        if record.stage_status.get(stage) in ("planned", "not_started", "not_applicable"):
            continue
        if stage_is_stale(record, stage, current_fingerprint):
            record.stage_stale[stage] = True
            if record.stage_status.get(stage) != "stale":
                record.stage_status[stage] = "stale"
                changed.append(stage)
        else:
            record.stage_stale[stage] = False
    return changed
