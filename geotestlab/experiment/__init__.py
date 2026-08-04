"""Experiment identity, fingerprints, stage status, design freeze, and export.

Pure, Streamlit-free modules for the local serialisable experiment record
(no database): identity, fingerprints, stages, records, stale, freeze, export.
"""

from geotestlab.experiment.export import build_experiment_export
from geotestlab.experiment.fingerprints import (
    canonical_json,
    compute_input_fingerprint,
)
from geotestlab.experiment.freeze import (
    active_frozen_version,
    freeze_design,
    is_frozen,
    planned_vs_analysed,
)
from geotestlab.experiment.identity import new_experiment_id, utc_now_iso
from geotestlab.experiment.records import (
    ExperimentRecord,
    add_note,
    create_experiment_record,
    record_stage_result,
    set_stage_status,
    stage_has_result,
    touch,
    update_inputs,
)
from geotestlab.experiment.stages import (
    STAGE_KEYS,
    STAGE_LABELS,
    STAGE_STATUSES,
    default_stage_status,
    stage_label,
)
from geotestlab.experiment.stale import (
    compute_stale_flags,
    propagate_staleness,
    stage_is_stale,
)

__all__ = [
    "ExperimentRecord",
    "STAGE_KEYS",
    "STAGE_LABELS",
    "STAGE_STATUSES",
    "active_frozen_version",
    "add_note",
    "build_experiment_export",
    "canonical_json",
    "compute_input_fingerprint",
    "compute_stale_flags",
    "create_experiment_record",
    "default_stage_status",
    "freeze_design",
    "is_frozen",
    "new_experiment_id",
    "planned_vs_analysed",
    "propagate_staleness",
    "record_stage_result",
    "set_stage_status",
    "stage_has_result",
    "stage_is_stale",
    "stage_label",
    "touch",
    "update_inputs",
    "utc_now_iso",
]
