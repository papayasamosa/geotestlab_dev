"""Streamlit entry point for effect-plausibility evidence scenarios."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from geotestlab.effect.plausibility import (
    EffectEvidence,
    EffectPlausibilityStatus,
    EffectScenario,
    EvidenceQuality,
    EvidenceType,
    assess_effect_plausibility,
    effect_result_is_stale,
)
from geotestlab.ui.components import render_technical_details


def render_effect_plausibility_tab() -> None:
    """Render evidence scenarios without producing an integrated recommendation."""

    st.subheader("🎯 Effect Plausibility")
    st.caption(
        "Connect explicit effectiveness evidence to the statistical MDE. This stage does not "
        "infer KPI impact from media delivery and does not combine effect, power and delivery "
        "into one recommendation score."
    )
    power_result = st.session_state.get("production_power_result")
    delivery_result = st.session_state.get("media_delivery_result")
    power_mde = getattr(power_result, "mde", None) if power_result else None
    power_direction = getattr(power_result, "side", None) if power_result else None
    direction_options = ("one_sided_positive", "one_sided_negative", "two_sided")
    if power_mde is not None:
        st.metric("Minimum detectable effect (from Check design)", f"{power_mde:.2f}%")
    else:
        st.caption(
            "No power-stage MDE available yet. Complete Check design first, or enter one "
            "under Advanced below."
        )
    if delivery_result is not None:
        st.caption(f"Delivery status is tracked separately: {delivery_result.status.value}.")

    no_evidence = st.checkbox(
        "I do not have effectiveness evidence for this test",
        help="Statistical detectability and media delivery remain assessed on their own steps; "
        "spend sufficiency for a KPI effect stays explicitly unknown without a bridge.",
    )
    if no_evidence:
        st.info(
            "Effect plausibility: unknown without an effectiveness bridge. Statistical "
            "detectability and media delivery are still evaluated separately."
        )
        st.session_state.effect_plausibility_evidence = None
        st.session_state.effect_plausibility_result = None
        return

    with st.form("effect_plausibility_form"):
        evidence_type = st.selectbox(
            "Effectiveness evidence type",
            tuple(item.value for item in EvidenceType),
            format_func=lambda value: value.replace("_", " ").title(),
        )
        quality = st.selectbox(
            "Evidence quality",
            tuple(item.value for item in EvidenceQuality),
            format_func=lambda value: value.title(),
            index=1,
        )
        source = st.text_input(
            "Evidence source", help="Name the study, forecast, model or assumption."
        )
        source_date_value = st.date_input("Evidence date (optional)", value=None)
        with st.expander("Override inherited MDE/direction (advanced)", expanded=False):
            mde = st.number_input(
                "MDE for comparison (%)",
                min_value=0.0,
                value=float(power_mde) if power_mde is not None else 0.0,
                step=0.5,
                help="Inherited from the Check design step's power result; override only for expert review.",
            )
            effect_direction = st.selectbox(
                "Effect direction for comparison",
                direction_options,
                index=direction_options.index(power_direction)
                if power_direction in direction_options
                else 2,
                format_func=lambda value: value.replace("_", " ").title(),
                help="Preserve the power-stage one-sided hypothesis when comparing expected uplift with MDE.",
            )
        st.markdown("#### Expected KPI-uplift scenarios")
        low_col, central_col, high_col = st.columns(3)
        with low_col:
            low = st.number_input("Low uplift (%)", min_value=-100.0, value=0.0, step=0.5)
        with central_col:
            central = st.number_input("Central uplift (%)", min_value=-100.0, value=5.0, step=0.5)
        with high_col:
            high = st.number_input("High uplift (%)", min_value=-100.0, value=10.0, step=0.5)
        adjusted = st.checkbox(
            "Evidence is adjusted or outlier-excluded",
            help="Adjusted estimates cannot silently become the central scenario.",
        )
        central_approved = st.checkbox(
            "Explicitly approve adjusted estimate as central scenario",
            disabled=not adjusted,
        )
        notes = st.text_area("Evidence notes and bridge assumptions")
        run_effect = st.form_submit_button("▶ Assess effect plausibility", type="primary")

    if not source.strip() and not run_effect:
        evidence = None
        evidence_error = None
    else:
        try:
            evidence = EffectEvidence(
                evidence_type=evidence_type,
                quality=quality,
                source=source,
                source_date=source_date_value.isoformat() if source_date_value else None,
                scenarios=(
                    EffectScenario("low", low),
                    EffectScenario("central", central),
                    EffectScenario("high", high),
                ),
                adjusted=adjusted,
                central_approved=central_approved,
                notes=notes,
            )
            evidence_error = None
        except ValueError as exc:
            evidence = None
            evidence_error = str(exc)
    if evidence_error:
        st.error(evidence_error)
    if run_effect and evidence is not None:
        try:
            result = assess_effect_plausibility(
                evidence,
                mde_pct=float(mde) if mde > 0 else None,
                effect_direction=effect_direction,
                delivery_status=delivery_result.status.value if delivery_result else None,
                delivery_fingerprint=(
                    delivery_result.input_fingerprint if delivery_result else None
                ),
            )
            st.session_state.effect_plausibility_evidence = evidence
            st.session_state.effect_plausibility_result = result
        except (TypeError, ValueError, KeyError) as exc:
            st.error(f"Effect plausibility could not be assessed: {exc}")

    result = st.session_state.get("effect_plausibility_result")
    if result is None:
        st.info(
            "Enter an explicit evidence source and low/central/high uplift scenarios to assess "
            "effect plausibility. Without a bridge, the status remains unknown."
        )
        return

    if result.status is EffectPlausibilityStatus.EVIDENCE_BACKED:
        st.success("Effect plausibility: evidence-backed bridge recorded.")
    elif result.status is EffectPlausibilityStatus.CONDITIONAL:
        st.warning("Effect plausibility: conditional on the recorded assumption bridge.")
    elif result.status is EffectPlausibilityStatus.BLOCKED:
        st.error("Effect plausibility: blocked until the evidence assumptions are corrected.")
    else:
        st.info("Effect plausibility: unknown without an effectiveness bridge.")
    if result.blockers:
        for blocker in result.blockers:
            st.error(blocker)
    for warning in result.warnings:
        st.warning(warning)

    current_mde = float(mde) if mde > 0 else None
    stored_evidence = st.session_state.get("effect_plausibility_evidence")
    st.session_state.effect_plausibility_current_evidence = evidence
    st.session_state.effect_plausibility_current_mde = current_mde
    st.session_state.effect_plausibility_current_direction = effect_direction
    if stored_evidence is not None:
        stale = effect_result_is_stale(
            result,
            stored_evidence,
            current_mde,
            effect_direction,
            delivery_status=delivery_result.status.value if delivery_result else None,
            delivery_fingerprint=(delivery_result.input_fingerprint if delivery_result else None),
        )
        if stale:
            st.warning(
                "This effect-plausibility result is stale because evidence, MDE or the referenced "
                "delivery result changed. Re-run the assessment before using it."
            )

    comparison_frame = pd.DataFrame(
        [
            {
                "Scenario": comparison.label,
                "Expected uplift (%)": comparison.expected_uplift_pct,
                "MDE (%)": comparison.mde_pct,
                "Meets MDE": comparison.meets_mde,
                "Margin to MDE (pp)": comparison.margin_to_mde_pct,
            }
            for comparison in result.comparisons
        ]
    )
    if not comparison_frame.empty:
        st.dataframe(comparison_frame, width="stretch", hide_index=True)
    st.download_button(
        "⬇️ Download effect plausibility result (.json)",
        data=json.dumps(result.to_dict(), indent=2, default=str),
        file_name="effect_plausibility_result.json",
        mime="application/json",
        key="download_effect_plausibility_result",
    )
    st.caption(f"Evidence source: {result.evidence.source if result.evidence else 'none'}")
    render_technical_details("Technical record", {"input_fingerprint": result.input_fingerprint})
