"""Production-facing power contract.

The experimental evidence harness remains in :mod:`geotestlab.power`. This
subpackage is the narrow, typed boundary that accepts the canonical regional
KPI dataset, records approved methodology provenance, and returns a result
that is safe to persist in an experiment record.
"""

from geotestlab.power.production.models import (
    APPROVED_EVIDENCE_COMMIT,
    APPROVED_METHODOLOGY_VERSION,
    PRODUCTION_POWER_CONTRACT_VERSION,
    ProductionPowerConfig,
    ProductionPowerResult,
)
from geotestlab.power.production.service import (
    production_input_fingerprint,
    production_result_is_stale,
    production_stage_is_stale,
    run_production_power,
)

__all__ = [
    "APPROVED_EVIDENCE_COMMIT",
    "APPROVED_METHODOLOGY_VERSION",
    "PRODUCTION_POWER_CONTRACT_VERSION",
    "ProductionPowerConfig",
    "ProductionPowerResult",
    "production_input_fingerprint",
    "production_result_is_stale",
    "production_stage_is_stale",
    "run_production_power",
]
