"""Experiment identity, fingerprints, stage status, design freeze, and export.

Pure, Streamlit-free modules for the local serialisable experiment record
(no database): identity, content digests, fingerprints, stages, records, stale,
freeze, export.
"""

from geotestlab.experiment.content import (
    analytical_data_digest,
    build_content_digests,
    candidate_universe_digest,
    canonical_frame,
    market_sheet_digest,
    material_file_identity,
    sha256_bytes,
    sha256_content,
)
from geotestlab.experiment.export import (
    EXPORT_SCHEMA_VERSION,
    build_experiment_export,
    build_stakeholder_summary,
    build_technical_summary,
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
    build_frozen_data_quality_summary,
    build_frozen_matching_section,
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
from geotestlab.experiment.reproducibility import (
    REPRODUCIBILITY_SCHEMA_VERSION,
    build_reproducibility_metadata,
    dependency_set_identity,
    installed_dependency_versions,
    mark_loaded_from_export,
    repository_identity,
    source_availability,
)
from geotestlab.experiment.result_summaries import build_unified_result_summaries
from geotestlab.experiment.stages import (
    STAGE_KEYS,
    STAGE_LABELS,
    STAGE_STATUSES,
    default_stage_status,
    observed_impact_completed,
    stage_label,
)
from geotestlab.experiment.stale import (
    compute_stale_flags,
    propagate_staleness,
    stage_is_stale,
)
from geotestlab.experiment.version import DEV_TOOL_VERSION, tool_version

__all__ = [
    "DEV_TOOL_VERSION",
    "EXPORT_SCHEMA_VERSION",
    "ExperimentRecord",
    "FROZEN_SCHEMA_VERSION",
    "FrozenVersion",
    "REPRODUCIBILITY_SCHEMA_VERSION",
    "RECORD_SCHEMA_VERSION",
    "STAGE_KEYS",
    "STAGE_LABELS",
    "STAGE_STATUSES",
    "active_frozen_version",
    "add_note",
    "analytical_data_digest",
    "build_content_digests",
    "build_experiment_export",
    "build_frozen_data_quality_summary",
    "build_frozen_matching_section",
    "build_reproducibility_metadata",
    "build_stakeholder_summary",
    "build_technical_summary",
    "build_unified_result_summaries",
    "candidate_universe_digest",
    "canonical_frame",
    "canonical_json",
    "compute_input_fingerprint",
    "compute_stale_flags",
    "create_experiment_record",
    "default_stage_status",
    "dependency_set_identity",
    "freeze_design",
    "is_frozen",
    "installed_dependency_versions",
    "load_experiment_record",
    "load_experiment_record_from_export",
    "mark_loaded_from_export",
    "market_sheet_digest",
    "material_file_identity",
    "new_experiment_id",
    "observed_impact_completed",
    "planned_vs_analysed",
    "propagate_staleness",
    "record_stage_method_result",
    "record_stage_result",
    "repository_identity",
    "set_stage_status",
    "sha256_bytes",
    "sha256_content",
    "stage_has_result",
    "stage_is_stale",
    "stage_label",
    "source_availability",
    "tool_version",
    "touch",
    "update_inputs",
    "utc_now_iso",
]
