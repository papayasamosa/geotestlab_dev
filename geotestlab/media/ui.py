"""Streamlit entry point for the media-delivery feasibility stage."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from geotestlab.media.delivery import (
    DeliveryStatus,
    DeliveryThresholds,
    ExperimentMediaScope,
    assess_media_delivery,
    delivery_result_is_stale,
)
from geotestlab.media.profiles import (
    INPUT_PROVENANCES,
    InputProvenance,
    MediaPlan,
    MediaValue,
    list_platform_profiles,
)


def _optional_number(value: float) -> float | None:
    return float(value) if value > 0 else None


def _optional_text(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def _parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_weekly_pattern(value: str) -> tuple[dict[str, float] | None, str | None]:
    cleaned = value.strip()
    if not cleaned:
        return None, None
    try:
        amounts = [float(item.strip()) for item in cleaned.split(",")]
    except ValueError:
        return None, "Weekly budget pattern must be comma-separated non-negative numbers."
    if any(amount < 0 for amount in amounts):
        return None, "Weekly budget pattern must not contain negative values."
    return {f"week_{index}": amount for index, amount in enumerate(amounts, start=1)}, None


def _media_value(
    value: Any,
    provenance: InputProvenance,
    source: str | None = None,
    source_date: str | None = None,
) -> MediaValue | None:
    if value is None or value == "":
        return None
    return MediaValue(value, provenance, source=source, source_date=source_date)


def _current_media_plan(
    profile_id: str,
    provenance: InputProvenance,
    budget: float,
    weekly_pattern: str,
    cpm: float,
    impressions: float,
    reach: float,
    frequency: float,
    eligible_audience: float,
    campaign_objective: str,
    optimisation_event: str,
    targeting_restrictions: str,
    geographic_targeting_method: str,
    existing_activity: str,
    spillover: str,
    forecast_source: str,
    forecast_date: str,
) -> tuple[MediaPlan | None, str | None]:
    parsed_pattern, pattern_error = _parse_weekly_pattern(weekly_pattern)
    if pattern_error:
        return None, pattern_error
    values: dict[str, MediaValue] = {}
    value_source = _optional_text(forecast_source)
    value_source_date = _optional_text(forecast_date)
    for key, value in (
        ("total_budget", _optional_number(budget)),
        ("cpm", _optional_number(cpm)),
        ("impressions", _optional_number(impressions)),
        ("reach", _optional_number(reach)),
        ("frequency", _optional_number(frequency)),
        ("eligible_audience", _optional_number(eligible_audience)),
        ("campaign_objective", _optional_text(campaign_objective)),
        ("optimisation_event", _optional_text(optimisation_event)),
        ("geographic_targeting_method", _optional_text(geographic_targeting_method)),
        ("existing_activity_in_control", _optional_text(existing_activity)),
        ("spillover_contamination", _optional_text(spillover)),
        ("forecast_source", _optional_text(forecast_source)),
        ("forecast_date", _optional_text(forecast_date)),
    ):
        media_value = _media_value(value, provenance, value_source, value_source_date)
        if media_value is not None:
            values[key] = media_value
    if parsed_pattern is not None:
        values["weekly_budget_pattern"] = MediaValue(
            parsed_pattern,
            provenance,
            source=value_source,
            source_date=value_source_date,
        )
    restrictions = _parse_list(targeting_restrictions)
    if restrictions:
        values["targeting_restrictions"] = MediaValue(
            restrictions,
            provenance,
            source=value_source,
            source_date=value_source_date,
        )
    return MediaPlan(profile_id=profile_id, values=values), None


def render_media_delivery_tab() -> None:
    """Render delivery feasibility independently from statistical power."""

    st.subheader("📣 Media Delivery Feasibility")
    st.caption(
        "Assess planned media delivery against explicit thresholds. Delivery status is separate "
        "from statistical power and does not claim that exposure creates incremental KPI impact."
    )
    profile_options = list_platform_profiles()
    profile_labels = {profile.profile_id: profile.display_name for profile in profile_options}
    snapshot = st.session_state.get("match_run_snapshot") or {}
    if snapshot.get("test_geos") or snapshot.get("selected_controls"):
        st.info(
            "Analytical design scope: "
            f"{len(snapshot.get('test_geos', ()))} test region(s), "
            f"{len(snapshot.get('selected_controls', ()))} control region(s). "
            "Media delivery remains a separate stage."
        )

    with st.form("media_delivery_form"):
        profile_id = st.selectbox(
            "Platform profile",
            tuple(profile_labels),
            format_func=profile_labels.__getitem__,
        )
        provenance = InputProvenance(
            st.selectbox(
                "Default input provenance",
                INPUT_PROVENANCES,
                format_func=lambda value: value.replace("_", " ").title(),
                help="Applied to values entered in this form; calculated outputs are labelled separately.",
            )
        )
        budget_col, cpm_col, impression_col = st.columns(3)
        with budget_col:
            budget = st.number_input("Total budget", min_value=0.0, value=0.0, step=100.0)
        with cpm_col:
            cpm = st.number_input("CPM", min_value=0.0, value=0.0, step=0.5)
        with impression_col:
            impressions = st.number_input(
                "Impressions (optional)", min_value=0.0, value=0.0, step=1000.0
            )
        weekly_pattern = st.text_input(
            "Weekly budget pattern (optional)",
            placeholder="e.g. 1000, 1500, 1500",
            help="Comma-separated planned weekly amounts; used to calculate total budget when supplied.",
        )
        reach_col, frequency_col, audience_col = st.columns(3)
        with reach_col:
            reach = st.number_input("Reach (optional)", min_value=0.0, value=0.0, step=100.0)
        with frequency_col:
            frequency = st.number_input("Frequency (optional)", min_value=0.0, value=0.0, step=0.1)
        with audience_col:
            eligible_audience = st.number_input(
                "Eligible audience (optional)", min_value=0.0, value=0.0, step=100.0
            )

        objective_col, event_col = st.columns(2)
        with objective_col:
            campaign_objective = st.text_input("Campaign objective")
        with event_col:
            optimisation_event = st.text_input("Optimisation event")
        targeting_restrictions = st.text_input("Targeting restrictions (comma-separated, optional)")
        geographic_targeting_method = st.text_input("Geographic targeting method")
        control_col, spillover_col = st.columns(2)
        with control_col:
            existing_activity = st.text_input("Existing activity in control")
        with spillover_col:
            spillover = st.text_input("Spillover or contamination assumption")
        source_col, date_col = st.columns(2)
        with source_col:
            forecast_source = st.text_input("Forecast source")
        with date_col:
            forecast_date = st.text_input("Forecast date (ISO, optional)")

        st.markdown("#### Delivery thresholds and analytical scope")
        threshold_col1, threshold_col2, threshold_col3 = st.columns(3)
        with threshold_col1:
            min_impressions = st.number_input(
                "Minimum impressions", min_value=0.0, value=0.0, step=1000.0
            )
        with threshold_col2:
            min_reach = st.number_input("Minimum reach", min_value=0.0, value=0.0, step=100.0)
        with threshold_col3:
            min_reach_percentage = st.number_input(
                "Minimum reach (%)", min_value=0.0, max_value=100.0, value=0.0, step=1.0
            )
        excluded_regions_text = st.text_input(
            "Exclude geographies from the experiment (comma-separated)"
        )
        ordinary_media_allowed = st.checkbox(
            "Allow ordinary media to continue in excluded geographies", value=True
        )
        run_delivery = st.form_submit_button("▶ Assess media delivery", type="primary")

    plan, plan_error = _current_media_plan(
        profile_id,
        provenance,
        budget,
        weekly_pattern,
        cpm,
        impressions,
        reach,
        frequency,
        eligible_audience,
        campaign_objective,
        optimisation_event,
        targeting_restrictions,
        geographic_targeting_method,
        existing_activity,
        spillover,
        forecast_source,
        forecast_date,
    )
    thresholds = DeliveryThresholds(
        min_impressions=_optional_number(min_impressions),
        min_reach=_optional_number(min_reach),
        min_reach_percentage=_optional_number(min_reach_percentage),
    )
    scope = ExperimentMediaScope(
        excluded_from_experiment=tuple(_parse_list(excluded_regions_text)),
        ordinary_media_allowed_in_excluded_regions=ordinary_media_allowed,
    )
    if plan_error:
        st.error(plan_error)
    if run_delivery and plan is not None:
        try:
            result = assess_media_delivery(plan, thresholds, scope)
            st.session_state.media_delivery_plan = plan
            st.session_state.media_delivery_thresholds = thresholds
            st.session_state.media_delivery_scope = scope
            st.session_state.media_delivery_result = result
        except (TypeError, ValueError, KeyError) as exc:
            st.error(f"Media delivery could not be assessed: {exc}")

    result = st.session_state.get("media_delivery_result")
    if result is None:
        st.info("Enter the available delivery inputs and assess the plan to see a delivery status.")
        return

    if plan is not None and not plan_error:
        try:
            stale = delivery_result_is_stale(result, plan, thresholds, scope)
        except (TypeError, ValueError, KeyError):
            stale = True
        if stale:
            st.warning(
                "This media delivery result is stale because delivery inputs, thresholds or "
                "analytical scope changed. Re-run the assessment before using it."
            )

    if result.status is DeliveryStatus.FEASIBLE:
        st.success("Delivery status: feasible against the selected thresholds.")
    elif result.status is DeliveryStatus.NOT_FEASIBLE:
        st.error("Delivery status: not feasible against the selected thresholds.")
    elif result.status is DeliveryStatus.INCOMPLETE:
        st.warning("Delivery status: incomplete; add the missing delivery inputs.")
    else:
        st.error("Delivery status: blocked by invalid or unsafe delivery inputs.")
    if result.blockers:
        for blocker in result.blockers:
            st.error(blocker)
    if result.missing_fields:
        st.warning("Missing: " + "; ".join(result.missing_fields))
    for warning in result.warnings:
        st.warning(warning)

    fields = []
    for key, media_value in sorted(result.values.items()):
        fields.append(
            {
                "Field": key,
                "Value": media_value.value,
                "Provenance": media_value.provenance.value,
                "Source": media_value.source,
            }
        )
    st.dataframe(pd.DataFrame(fields), width="stretch", hide_index=True)
    st.download_button(
        "⬇️ Download media delivery result (.json)",
        data=json.dumps(result.to_dict(), indent=2, default=str),
        file_name="media_delivery_result.json",
        mime="application/json",
        key="download_media_delivery_result",
    )
    st.caption(
        f"Profile: {result.profile_id} · input fingerprint: {result.input_fingerprint} · "
        f"calculated fields: {', '.join(result.calculated_fields) or 'none'}"
    )
