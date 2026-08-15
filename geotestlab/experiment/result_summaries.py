"""Build the unified, serialisable result section of an experiment export."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping, Sequence


def _serialise(value: Any) -> Any:
    """Convert typed result contracts and common containers to JSON values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "to_dict"):
        return _serialise(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_serialise(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _selected_values(value: Mapping[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: _serialise(value[key]) for key in keys if key in value}


def build_unified_result_summaries(
    *,
    validation_results: Mapping[str, Any] | None = None,
    bayesian_results: Mapping[str, Any] | None = None,
    power_result: Any = None,
    power_config: Any = None,
    media_delivery_result: Any = None,
    media_delivery_plan: Any = None,
    media_delivery_thresholds: Any = None,
    media_delivery_scope: Any = None,
    effect_plausibility_result: Any = None,
    recommendation_result: Any = None,
    recommendation_scenarios: Sequence[Any] = (),
    recommendation_objective: Any = None,
) -> dict[str, dict[str, Any]]:
    """Return all available analytical results under stable stage keys.

    The function keeps validation and Bayesian summaries intentionally compact,
    while preserving the typed power, delivery, effect and recommendation
    contracts plus their explicit input objects. Stale status and fingerprints
    remain in the experiment record's stage section alongside these summaries.
    """

    summaries: dict[str, dict[str, Any]] = {}
    validation = validation_results or {}
    if validation.get("results"):
        summaries["counterfactual_validation"] = {
            str(method): _selected_values(
                result,
                (
                    "corr",
                    "r2",
                    "smape",
                    "n_selected",
                    "rolling_smape_mean",
                    "counterfactual_reliability",
                ),
            )
            for method, result in validation["results"].items()
            if isinstance(result, Mapping)
        }

    bayesian = bayesian_results or {}
    if bayesian:
        summaries["observed_impact"] = _selected_values(
            bayesian,
            (
                "mean_uplift",
                "uplift_pct",
                "prob_pos",
                "uplift_pi_lower",
                "uplift_pi_upper",
                "corr",
                "r2",
                "smape",
            ),
        )

    if power_result is not None:
        power_summary = _serialise(power_result)
        if not isinstance(power_summary, dict):
            power_summary = {"result": power_summary}
        if power_config is not None:
            power_summary["config"] = _serialise(power_config)
        summaries["statistical_power"] = power_summary

    if media_delivery_result is not None:
        delivery_summary = _serialise(media_delivery_result)
        if not isinstance(delivery_summary, dict):
            delivery_summary = {"result": delivery_summary}
        if media_delivery_plan is not None:
            delivery_summary["plan"] = _serialise(media_delivery_plan)
        if media_delivery_thresholds is not None:
            delivery_summary["thresholds"] = _serialise(media_delivery_thresholds)
        if media_delivery_scope is not None:
            delivery_summary["scope"] = _serialise(media_delivery_scope)
        summaries["media_delivery"] = delivery_summary

    if effect_plausibility_result is not None:
        effect_summary = _serialise(effect_plausibility_result)
        summaries["effect_plausibility"] = (
            effect_summary if isinstance(effect_summary, dict) else {"result": effect_summary}
        )

    if recommendation_result is not None:
        recommendation_summary = _serialise(recommendation_result)
        if not isinstance(recommendation_summary, dict):
            recommendation_summary = {"result": recommendation_summary}
        recommendation_summary["scenarios"] = [
            _serialise(scenario) for scenario in recommendation_scenarios
        ]
        if recommendation_objective is not None:
            recommendation_summary["objective"] = _serialise(recommendation_objective)
        summaries["design_recommendation"] = recommendation_summary

    return summaries
