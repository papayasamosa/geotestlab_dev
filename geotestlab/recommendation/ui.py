"""Streamlit entry point for the integrated design recommendation stage."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from geotestlab.effect.plausibility import effect_result_is_stale
from geotestlab.media.delivery import delivery_result_is_stale
from geotestlab.power.production import production_result_is_stale
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
    "stale",
)


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _stage_quality_status(key: str) -> str:
    """Return a quality status only when an upstream diagnostic supports it."""

    record = st.session_state.get("experiment_record")
    if isinstance(record, dict):
        explicit = (record.get("quality_status") or {}).get(key)
        if explicit:
            return str(explicit)
    if key == "counterfactual_validation":
        results = (st.session_state.get("validation_results") or {}).get("results") or {}
        reliabilities = [
            str(result.get("counterfactual_reliability", "")).lower()
            for result in results.values()
            if isinstance(result, dict)
        ]
        if reliabilities and all("high" in value or "moderate" in value for value in reliabilities):
            return "supported"
    return "not_evaluated"


def _delivery_is_current(result) -> bool:
    plan = st.session_state.get("media_delivery_plan")
    thresholds = st.session_state.get("media_delivery_thresholds")
    scope = st.session_state.get("media_delivery_scope")
    if result is None or plan is None or thresholds is None or scope is None:
        return False
    try:
        return not delivery_result_is_stale(result, plan, thresholds, scope)
    except (TypeError, ValueError, KeyError):
        return False


def _power_is_current(result) -> bool:
    dataset = st.session_state.get("kpi_regional_dataset")
    config = st.session_state.get("production_power_config")
    if result is None or dataset is None or config is None:
        return False
    try:
        return not production_result_is_stale(result, dataset, config)
    except (TypeError, ValueError, KeyError):
        return False


def _effect_is_current(result, delivery_current: bool) -> bool:
    evidence = st.session_state.get("effect_plausibility_current_evidence")
    if evidence is None:
        evidence = st.session_state.get("effect_plausibility_evidence")
    delivery = st.session_state.get("media_delivery_result")
    if result is None or evidence is None or (delivery is not None and not delivery_current):
        return False
    try:
        return not effect_result_is_stale(
            result,
            evidence,
            st.session_state.get("effect_plausibility_current_mde"),
            st.session_state.get("effect_plausibility_current_direction", "two_sided"),
            delivery_status=delivery.status.value if delivery else None,
            delivery_fingerprint=delivery.input_fingerprint if delivery else None,
        )
    except (TypeError, ValueError, KeyError):
        return False


def _candidate_power_is_current(power, dataset) -> bool:
    """Check candidate power against the canonical source fingerprint.

    Candidate power uses a candidate-specific production configuration, so the
    selected-design ``production_power_config`` is not a valid staleness check.
    The production result's source fingerprint is the shared identity that can
    be checked without rebuilding the candidate configuration.
    """

    source_fingerprint = getattr(power, "source_data_fingerprint", None)
    dataset_fingerprint = getattr(dataset, "source_data_fingerprint", None)
    return bool(
        source_fingerprint and dataset_fingerprint and source_fingerprint == dataset_fingerprint
    )


def _candidate_constraint_status(candidate, config) -> str:
    """Return the constraint status for a retained candidate design."""

    constraints = getattr(config, "constraints", None) if config is not None else None
    if constraints is None:
        return "not_evaluated"

    test_regions = set(getattr(candidate, "test_regions", ()) or ())
    control_regions = set(getattr(candidate, "control_regions", ()) or ())
    checks = (
        set(getattr(constraints, "force_test_include", ())) <= test_regions,
        set(getattr(constraints, "force_control_include", ())) <= control_regions,
        not set(getattr(constraints, "exclude_from_both", ())) & (test_regions | control_regions),
        not set(getattr(constraints, "test_only_exclude", ())) & test_regions,
        not set(getattr(constraints, "control_only_exclude", ())) & control_regions,
        not test_regions & control_regions,
    )
    return "pass" if all(checks) else "blocked"


def _delivery_cost(delivery, current: bool) -> float | None:
    if delivery is None or not current:
        return None
    budget = getattr(delivery, "values", {}).get("total_budget")
    return _number(getattr(budget, "value", budget)) if budget is not None else None


def _effect_meets_mde(effect, current: bool, candidate_mde: float | None) -> bool | None:
    """Compare the shared central effect with this candidate's own MDE."""

    if effect is None or not current or candidate_mde is None:
        return None
    central = next((item for item in effect.comparisons if item.label == "central"), None)
    if central is None:
        return None
    direction = st.session_state.get(
        "effect_plausibility_current_direction",
        getattr(effect, "effect_direction", "two_sided"),
    )
    expected = float(central.expected_uplift_pct)
    effect_distance = (
        expected
        if direction == "one_sided_positive"
        else -expected
        if direction == "one_sided_negative"
        else abs(expected)
    )
    return effect_distance >= candidate_mde


def _result_payload(result) -> Any:
    """Return an export-safe upstream result payload when available."""

    if result is None:
        return None
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(result, Mapping):
        return dict(result)
    return str(result)


def _upstream_scenarios() -> tuple[DesignScenario, ...]:
    """Adapt typed scenario-sizing candidates into recommendation contracts."""

    sizing = st.session_state.get("power_scenario_result")
    if sizing is None or not getattr(sizing, "candidates", ()):
        return ()

    dataset = st.session_state.get("kpi_regional_dataset")
    config = st.session_state.get("power_scenario_config")
    delivery = st.session_state.get("media_delivery_result")
    effect = st.session_state.get("effect_plausibility_result")
    delivery_current = _delivery_is_current(delivery)
    effect_current = _effect_is_current(effect, delivery_current)
    cost = _delivery_cost(delivery, delivery_current)
    delivery_status = (
        str(getattr(getattr(delivery, "status", None), "value", "not_evaluated"))
        if delivery_current
        else ("stale" if delivery is not None else "not_evaluated")
    )
    effect_status = (
        str(getattr(getattr(effect, "status", None), "value", "not_evaluated"))
        if effect_current
        else ("stale" if effect is not None else "not_evaluated")
    )

    scenarios: list[DesignScenario] = []
    for index, candidate in enumerate(sizing.candidates, start=1):
        power = getattr(candidate, "power_result", None)
        power_current = _candidate_power_is_current(power, dataset)
        power_values = tuple(getattr(power, "power_at_target_effects", ()) or ())
        target_power = _number(getattr(power, "target_power", None))
        power_meets = (
            bool(power_values)
            and target_power is not None
            and all(float(value) >= target_power for value in power_values)
            if power_current
            else None
        )
        power_status = (
            str(getattr(power, "support_status", "not_evaluated"))
            if power_current
            else ("stale" if power is not None else "not_evaluated")
        )
        history_periods = None
        sufficiency = getattr(power, "historical_data_sufficiency", {}) or {}
        if isinstance(sufficiency, Mapping):
            history_periods = _number(sufficiency.get("retained_periods"))
            history_periods = int(history_periods) if history_periods is not None else None

        blockers = tuple(
            str(item) for item in (getattr(candidate, "recommendation_blockers", ()) or ())
        )
        notes = blockers
        metadata = {
            "source": "power_scenario_result",
            "analyst_supplied": False,
            "metric": getattr(sizing, "metric", None),
            "market_size_measure": getattr(candidate, "market_size_measure", None),
            "total_market_size": getattr(sizing, "total_market_size", None),
            "requested_share": getattr(candidate, "requested_share", None),
            "actual_share": getattr(candidate, "actual_share", None),
            "share_difference": getattr(candidate, "share_difference", None),
            "test_regions": list(getattr(candidate, "test_regions", ()) or ()),
            "control_regions": list(getattr(candidate, "control_regions", ()) or ()),
            "planned_test_dates": list(getattr(candidate, "planned_test_dates", ()) or ()),
            "candidate": _result_payload(candidate),
            "power_result": _result_payload(power),
            "power_current": power_current,
            "delivery_result": _result_payload(delivery),
            "delivery_current": delivery_current,
            "effect_result": _result_payload(effect),
            "effect_current": effect_current,
            "source_data_fingerprint": getattr(power, "source_data_fingerprint", None),
            "delivery_input_fingerprint": getattr(delivery, "input_fingerprint", None),
            "effect_input_fingerprint": getattr(effect, "input_fingerprint", None),
        }
        scenarios.append(
            DesignScenario(
                scenario_id=f"candidate_{index}",
                size_metric=float(candidate.actual_share),
                duration_periods=int(candidate.duration_periods),
                cost=cost,
                match_status=str(candidate.design_assessment.match_status),
                counterfactual_status=str(candidate.design_assessment.counterfactual_status),
                power_status=power_status,
                power_usable=bool(getattr(power, "usable_for_recommendation", False))
                if power_current
                else False,
                power_meets_target=power_meets,
                delivery_status=delivery_status,
                effect_status=effect_status,
                effect_meets_mde=_effect_meets_mde(
                    effect,
                    effect_current,
                    _number(getattr(power, "mde", None)) if power_current else None,
                ),
                region_constraints_status=_candidate_constraint_status(candidate, config),
                history_periods=history_periods,
                notes=notes,
                metadata=metadata,
            )
        )
    return tuple(scenarios)


def _upstream_frame(scenarios: tuple[DesignScenario, ...]) -> pd.DataFrame:
    """Build the read-only candidate evidence table for the normal path."""

    return pd.DataFrame(
        [
            {
                "Scenario": scenario.scenario_id,
                "Actual test share": scenario.size_metric,
                "Duration": scenario.duration_periods,
                "Cost": scenario.cost,
                "Match": scenario.match_status,
                "Counterfactual": scenario.counterfactual_status,
                "Power": scenario.power_status,
                "Power usable": scenario.power_usable,
                "Power meets target": scenario.power_meets_target,
                "Delivery": scenario.delivery_status,
                "Effect": scenario.effect_status,
                "Effect meets MDE": scenario.effect_meets_mde,
                "Region constraints": scenario.region_constraints_status,
            }
            for scenario in scenarios
        ]
    )


def _manual_default_row() -> dict[str, Any]:
    power = st.session_state.get("production_power_result")
    delivery = st.session_state.get("media_delivery_result")
    effect = st.session_state.get("effect_plausibility_result")
    delivery_current = _delivery_is_current(delivery)
    effect_current = _effect_is_current(effect, delivery_current)
    power_current = _power_is_current(power)
    power_values = tuple(getattr(power, "power_at_target_effects", ()) or ())
    target_power = float(getattr(power, "target_power", 0.8) or 0.8) if power else 0.8
    power_meets = bool(power_values and all(float(value) >= target_power for value in power_values))
    effect_meets = None
    if effect is not None:
        central = next((item for item in effect.comparisons if item.label == "central"), None)
        effect_meets = central.meets_mde if central is not None else None
    cost = None
    if delivery is not None and delivery_current:
        budget = delivery.values.get("total_budget")
        cost = _number(getattr(budget, "value", None)) if budget is not None else None
    power_status = (
        str(getattr(power, "support_status", "not_evaluated")) if power else "not_evaluated"
    )
    if not power_current:
        power_status = "stale" if power is not None else "not_evaluated"
    delivery_status = (
        str(getattr(getattr(delivery, "status", None), "value", "not_evaluated"))
        if delivery_current
        else ("stale" if delivery is not None else "not_evaluated")
    )
    effect_status = (
        str(getattr(getattr(effect, "status", None), "value", "not_evaluated"))
        if effect_current
        else ("stale" if effect is not None else "not_evaluated")
    )
    return {
        "scenario_id": "selected_design",
        "size_metric": 1.0,
        "duration_periods": int(getattr(power, "requested_test_periods", 1) or 1),
        "cost": cost,
        "match_status": _stage_quality_status("match_quality"),
        "counterfactual_status": _stage_quality_status("counterfactual_validation"),
        "power_status": power_status,
        "power_usable": bool(getattr(power, "usable_for_recommendation", False))
        if power_current
        else False,
        "power_meets_target": power_meets if power_current else None,
        "delivery_status": delivery_status,
        "effect_status": effect_status,
        "effect_meets_mde": effect_meets if effect_current else None,
        "region_constraints_status": "not_evaluated",
    }


def _scenario_from_row(row: dict[str, Any]) -> DesignScenario:
    cost = _number(row.get("cost"))
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    metadata = {
        **metadata,
        "source": "analyst_supplied",
        "analyst_supplied": True,
    }
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
        metadata=metadata,
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
    upstream_scenarios = _upstream_scenarios()
    if upstream_scenarios:
        st.info(
            "These candidates come from the typed scenario comparison. Gate statuses, actual "
            "shares, durations and power evidence are read-only here; rerun the upstream "
            "comparison to change them."
        )
        st.markdown("#### Upstream candidate evidence (read-only)")
        st.dataframe(_upstream_frame(upstream_scenarios), width="stretch", hide_index=True)
        form_context = st.container()
        scenarios: list[DesignScenario] = list(upstream_scenarios)
        edited = None
    else:
        st.info(
            "Run candidate scenario comparison in Power Analysis & Test Sizing first. "
            "Until then, only the explicitly labelled advanced/manual path is available."
        )
        form_context = st.expander("Advanced/manual scenario analysis", expanded=True)
        scenarios = []
        edited = None

    with form_context:
        if not upstream_scenarios:
            st.caption(
                "Advanced/manual mode: every candidate value is analyst-supplied and remains "
                "separate from upstream matching, validation and power results."
            )
        with st.form("design_recommendation_form"):
            objective = st.selectbox(
                "Recommendation objective",
                tuple(item.value for item in RecommendationObjective),
                format_func=lambda value: value.replace("_", " ").title(),
                help="The objective is explicit: smallest qualifying design or least-cost qualifying design.",
            )
            st.markdown("#### Candidate designs")
            if upstream_scenarios:
                st.caption("Candidate gate fields are supplied by the upstream scenario result.")
            else:
                edited = st.data_editor(
                    pd.DataFrame([_manual_default_row()]),
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
            run_recommendation = st.form_submit_button(
                "▶ Compare design candidates", type="primary"
            )

    parse_error = None
    if not upstream_scenarios:
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
            st.session_state.design_recommendation_stale = False
        except (TypeError, ValueError, KeyError) as exc:
            st.error(f"Design recommendation could not be assessed: {exc}")

    result = st.session_state.get("design_recommendation_result")
    if result is None:
        st.session_state.design_recommendation_stale = False
        st.info("No design comparison yet. Review the candidate gates and run the comparison.")
        return

    if parse_error or not scenarios:
        st.session_state.design_recommendation_stale = True
        st.warning(
            "The stored recommendation is stale because the current candidate table is empty "
            "or invalid. Add valid candidates and re-run the comparison."
        )
        return
    try:
        if recommendation_result_is_stale(
            result,
            scenarios,
            objective,
            override_scenario_id=override_id.strip() or None,
            override_reason=override_reason,
        ):
            st.session_state.design_recommendation_stale = True
            st.warning(
                "This recommendation is stale because candidate inputs, the objective or "
                "the override changed. Re-run the comparison before using it."
            )
            return
        st.session_state.design_recommendation_stale = False
    except (TypeError, ValueError, KeyError):
        st.session_state.design_recommendation_stale = True
        st.warning("The current candidate table could not reproduce the stored result.")
        return

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
        data=json.dumps(
            {
                "recommendation": result.to_dict(),
                "scenarios": [scenario.to_dict() for scenario in scenarios],
            },
            indent=2,
            default=str,
        ),
        file_name="design_recommendation.json",
        mime="application/json",
        key="download_design_recommendation",
    )
    st.caption(
        f"Objective: {result.objective.value} · input fingerprint: {result.input_fingerprint}"
    )
