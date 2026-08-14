"""Platform-aware media-plan contracts.

Media delivery is deliberately modelled outside the statistical power package.
The contracts here describe platform fields and provenance; delivery calculations
consume these contracts in a later workflow stage.
"""

from geotestlab.media.delivery import (
    DELIVERY_CONTRACT_VERSION,
    DeliveryAssessment,
    DeliveryStatus,
    DeliveryThresholds,
    ExperimentMediaScope,
    assess_media_delivery,
    delivery_input_fingerprint,
    delivery_result_is_stale,
)
from geotestlab.media.profiles import (
    INPUT_PROVENANCES,
    MEDIA_PLAN_SCHEMA_VERSION,
    PLATFORM_PROFILES,
    InputProvenance,
    MediaField,
    MediaPlan,
    MediaValue,
    PlatformProfile,
    get_platform_profile,
    list_platform_profiles,
)

__all__ = [
    "INPUT_PROVENANCES",
    "MEDIA_PLAN_SCHEMA_VERSION",
    "PLATFORM_PROFILES",
    "InputProvenance",
    "MediaField",
    "MediaPlan",
    "MediaValue",
    "PlatformProfile",
    "get_platform_profile",
    "list_platform_profiles",
    "DELIVERY_CONTRACT_VERSION",
    "DeliveryAssessment",
    "DeliveryStatus",
    "DeliveryThresholds",
    "ExperimentMediaScope",
    "assess_media_delivery",
    "delivery_input_fingerprint",
    "delivery_result_is_stale",
]
