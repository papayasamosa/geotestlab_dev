"""Integrated design recommendation contracts."""

from geotestlab.recommendation.recommendation import (
    RECOMMENDATION_SCHEMA_VERSION,
    DesignScenario,
    RecommendationObjective,
    RecommendationResult,
    RecommendationStatus,
    ScenarioAssessment,
    assess_design_recommendation,
    recommendation_input_fingerprint,
    recommendation_result_is_stale,
)

__all__ = [
    "RECOMMENDATION_SCHEMA_VERSION",
    "DesignScenario",
    "RecommendationObjective",
    "RecommendationResult",
    "RecommendationStatus",
    "ScenarioAssessment",
    "assess_design_recommendation",
    "recommendation_input_fingerprint",
    "recommendation_result_is_stale",
]
