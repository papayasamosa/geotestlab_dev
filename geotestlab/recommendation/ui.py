"""Streamlit entry point for the integrated design recommendation stage."""

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd
import streamlit as st

from geotestlab.recommendation import (
    DesignScenario,
    RecommendationObjective,
    RecommendationStatus,
    assess_design_recommendation,
    recommendation_result_is_stale,
)

_STATUS_OPTIONS = (
    "not_evaluated",
    "pass",
    "supported",
    "credible",
    "valid",
    "incomplete",
    "blocked",
    "not_feasible",
    "unknown",
    "conditional",
    "evidence_backed",
)


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _stage_status(key: str) -> str:
    record = st.session_state.get("experiment_record")
    if isinstance(record, dict):
        status = record.get("stage_status", {}).get(key)
        if status == "completed":
            return "supported"
    return "not_evaluated"


def _default_row() -> dict[str, Any]:
    power = st.session_state.get("production_power_result")
    delivery = st.session_state.get("media_delivery_result")
    effect = st.session_state.get("effect_plausibility_result")
    power_values = tuple(getattr(power, "power_at_target_effects", ()) or ())
    target_power = float(getattr(power, "target_power", 0.8) or 0.8) if power else 0.8
    power_meets = bool(power_values and all(float(value) >= target_power for value in power_values))
    effect_meets = None
    if effect is not None:
        central = next((item for item in effect.comparisons if item.label == "central"), None)
        effect_meets = central.meets_mde if central is not None else None
    cost = None
    if delivery is not None:
        budget = delivery.values.get("total_budget")
        cost = _number(getattr(budget, "value", None)) if budget is not None else None
    power_status = (
        str(getattr(power, "support_status", "not_evaluated")) if power else "not_evaluated"
    )
    delivery_status = str(getattr(getattr(delivery, "status", None), "value", "not_evaluated"))
    effect_status = str(getattr(getattr(effect, "status", None), "value", "not_evaluated"))
    return {
        "scenario_id": "selected_design",
        "size_metric": 1.0,
        "duration_periods": int(getattr(power, "requested_test_periods", 1) or 1),
        "cost": cost if cost is not None else 0.0,
        "match_status": _stage_status("match_quality"),
        "counterfactual_status": _stage_status("counterfactual_validation"),
        "power_status": power_status,
        "power_usable": bool(getattr(power, "usable_for_recommendation", False))
        if power
        else False,
        "power_meets_target": power_meets if power else None,
        "delivery_status": delivery_status,
        "effect_status": effect_status,
        "effect_meets_mde": effect_meets,
        "region_constraints_status": "not_evaluated",
    }


def _scenario_from_row(row: dict[str, Any]) -> DesignScenario:
    cost = _number(row.get("cost"))
    return DesignScenario(
        scenario_id=str(row.get("scenario_id", "")).strip(),
        size_metric=_number(row.get("size_metric"), 0.0),
        duration_periods=int(_number(row.get("duration_periods"), 0) or 0),
        cost=cost,
        match_status=str(row.get("match_status", "not_evaluated")),
        counterfactual_status=str(row.get("counterfactual_status", "not_evaluated")),
        power_status=str(row.get("power_status", "not_evaluated")),
        power_usable=bool(row.get("power_usable", False)),
        power_meets_target=(
            bool(row.get("power_meets_target"))
            if row.get("power_meets_target") is not None
            and not (
                isinstance(row.get("power_meets_target"), float)
                and math.isnan(row["power_meets_target"])
            )
            else None
        ),
        delivery_status=str(row.get("delivery_status", "not_evaluated")),
        effect_status=str(row.get("effect_status", "not_evaluated")),
        effect_meets_mde=(
            bool(row.get("effect_meets_mde"))
            if row.get("effect_meets_mde") is not None
            and not (
                isinstance(row.get("effect_meets_mde"), float)
                and math.isnan(row["effect_meets_mde"])
            )
            else None
        ),
        region_constraints_status=str(row.get("region_constraints_status", "not_evaluated")),
    )


def _assessment_frame(result) -> pd.DataFrame:
    rows = []
    for assessment in result.assessments:
        row = {
            "Scenario": assessment.scenario_id,
            "Qualifies": assessment.qualifies,
            "Conditional": assessment.conditional,
            "Size metric": assessment.size_metric,
            "Duration": assessment.duration_periods,
            "Cost": assessment.cost,
        }
        row.update({f"Gate: {key}": value for key, value in assessment.gate_statuses.items()})
        rows.append(row)
    return pd.DataFrame(rows)


def render_design_recommendation_tab() -> None:
    """Render explicit candidate comparison and limiting-factor output."""

    st.subheader("✅ Integrated Design Recommendation")
    st.caption(
        "Compare complete design candidates under an explicit objective. Match quality, "
        "counterfactual validation, power, delivery, effect plausibility, constraints, "
        "duration and cost remain separate gates; there is no composite score."
    )
    st.info(
        "Enter or review one row per candidate. A full recommendation requires every gate; "
        "a conditional effect bridge produces a clearly labelled conditional recommendation."
    )

    default_frame = pd.DataFrame([_default_row()])
    with st.form("design_recommendation_form"):
        objective = st.selectbox(
            "Recommendation objective",
            tuple(item.value for item in RecommendationObjective),
            format_func=lambda value: value.replace("_", " ").title(),
            help="The objective is explicit: smallest qualifying design or least-cost qualifying design.",
        )
        st.markdown("#### Candidate designs")
        edited = st.data_editor(
            default_frame,
            num_rows="dynamic",
            hide_index=True,
            key="design_recommendation_candidates",
            width="stretch",
        )
        override_id = st.text_input(
            "Override scenario ID (optional)",
            help="An override must include a reason and remains visible in the export.",
        )
        override_reason = st.text_area("Override reason (required when overriding)")
        run_recommendation = st.form_submit_button("▶ Compare design candidates", type="primary")

    scenarios: list[DesignScenario] = []
    parse_error = None
    try:
        scenarios = [_scenario_from_row(row) for row in edited.to_dict(orient="records")]
        scenarios = [scenario for scenario in scenarios if scenario.scenario_id]
    except (TypeError, ValueError, KeyError) as exc:
        parse_error = str(exc)
    if parse_error:
        st.error(f"Candidate inputs are invalid: {parse_error}")
    if run_recommendation and not parse_error:
        try:
            result = assess_design_recommendation(
                scenarios,
                objective,
                override_scenario_id=override_id.strip() or None,
                override_reason=override_reason,
            )
            st.session_state.design_recommendation_result = result
            st.session_state.design_recommendation_scenarios = tuple(scenarios)
            st.session_state.design_recommendation_objective = objective
        except (TypeError, ValueError, KeyError) as exc:
            st.error(f"Design recommendation could not be assessed: {exc}")

    result = st.session_state.get("design_recommendation_result")
    if result is None:
        st.info("No design comparison yet. Review the candidate gates and run the comparison.")
        return

    if scenarios:
        try:
            if recommendation_result_is_stale(
                result,
                scenarios,
                objective,
                override_scenario_id=override_id.strip() or None,
                override_reason=override_reason,
            ):
                st.warning(
                    "This recommendation is stale because candidate inputs, the objective or "
                    "the override changed. Re-run the comparison before using it."
                )
        except (TypeError, ValueError, KeyError):
            st.warning("The current candidate table could not be matched to the stored result.")

    if result.status is RecommendationStatus.RECOMMENDED:
        st.success(f"Recommended design: {result.selected_scenario_id}")
    elif result.status is RecommendationStatus.CONDITIONAL:
        st.warning(f"Conditional design recommendation: {result.selected_scenario_id}")
    elif result.status is RecommendationStatus.NO_QUALIFYING_DESIGN:
        st.error("No qualifying design. Review the limiting factors below.")
    else:
        st.info("Design recommendation is incomplete.")

    if result.selected_scenario_id:
        st.metric("Selected scenario", result.selected_scenario_id)
    if result.conditions:
        for condition in result.conditions:
            st.warning(condition)
    if result.limiting_factors:
        st.markdown("#### Limiting factors")
        for factor in result.limiting_factors:
            st.error(factor)
    st.markdown("#### Separate gate assessments")
    st.dataframe(_assessment_frame(result), width="stretch", hide_index=True)
    st.download_button(
        "⬇️ Download design recommendation (.json)",
        data=json.dumps(result.to_dict(), indent=2, default=str),
        file_name="design_recommendation.json",
        mime="application/json",
        key="download_design_recommendation",
    )
    st.caption(
        f"Objective: {result.objective.value} · input fingerprint: {result.input_fingerprint}"
    )
