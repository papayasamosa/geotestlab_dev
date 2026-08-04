"""Experiment identity, fingerprints, stage status, design freeze, and export.

Pure, Streamlit-free modules for the local serialisable experiment record
(no database): identity, content digests, fingerprints, stages, records, stale,
freeze, export.
"""

from geotestlab.experiment.content import (
    analytical_data_digest,
    build_content_digests,
    candidate_universe_digest,
    market_sheet_digest,
    sha256_bytes,
    sha256_content,
)
from geotestlab.experiment.export import (
    EXPORT_SCHEMA_VERSION,
    build_experiment_export,
    load_experiment_record_from_export,
)
from geotestlab.experiment.fingerprints import (
    canonical_json,
    compute_input_fingerprint,
)
from geotestlab.experiment.freeze import (
    FROZEN_SCHEMA_VERSION,
    FrozenVersion,
    active_frozen_version,
    freeze_design,
    is_frozen,
    planned_vs_analysed,
)
from geotestlab.experiment.identity import new_experiment_id, utc_now_iso
from geotestlab.experiment.records import (
    RECORD_SCHEMA_VERSION,
    ExperimentRecord,
    add_note,
    create_experiment_record,
    load_experiment_record,
    record_stage_method_result,
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
    "EXPORT_SCHEMA_VERSION",
    "ExperimentRecord",
    "FROZEN_SCHEMA_VERSION",
    "FrozenVersion",
    "RECORD_SCHEMA_VERSION",
    "STAGE_KEYS",
    "STAGE_LABELS",
    "STAGE_STATUSES",
    "active_frozen_version",
    "add_note",
    "analytical_data_digest",
    "build_content_digests",
    "build_experiment_export",
    "candidate_universe_digest",
    "canonical_json",
    "compute_input_fingerprint",
    "compute_stale_flags",
    "create_experiment_record",
    "default_stage_status",
    "freeze_design",
    "is_frozen",
    "load_experiment_record",
    "load_experiment_record_from_export",
    "market_sheet_digest",
    "new_experiment_id",
    "planned_vs_analysed",
    "propagate_staleness",
    "record_stage_method_result",
    "record_stage_result",
    "set_stage_status",
    "sha256_bytes",
    "sha256_content",
    "stage_has_result",
    "stage_is_stale",
    "stage_label",
    "touch",
    "update_inputs",
    "utc_now_iso",
]
