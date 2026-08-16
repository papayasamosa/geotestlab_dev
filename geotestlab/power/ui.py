"""Streamlit UI for selected-design and candidate scenario power sizing."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping

import pandas as pd
import streamlit as st

from geotestlab.data import MarketSizeMeasure
from geotestlab.matching import MatchConstraints
from geotestlab.power.production import (
    ProductionPowerConfig,
    production_result_is_stale,
    run_production_power,
)
from geotestlab.power.scenarios import ScenarioSizingConfig, size_power_scenarios

ExperimentRecordFactory = Callable[[], object]
ExperimentRecordSaver = Callable[[object], None]


def _power_region_groups() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the last executed test/control groups for selected-design power."""

    snapshot = st.session_state.get("match_run_snapshot") or {}
    test_regions = tuple(sorted(str(value) for value in snapshot.get("test_geos", ()) if value))
    control_regions = tuple(
        sorted(str(value) for value in snapshot.get("selected_controls", ()) if value)
    )
    if not test_regions:
        test_regions = tuple(
            sorted(str(value) for value in st.session_state.get("selected_experiment_regions", ()))
        )
    if not control_regions:
        controls = st.session_state.get("final_controls")
        geo_col = st.session_state.get("geo_col")
        if controls is not None and geo_col in controls.columns:
            control_regions = tuple(sorted(str(value) for value in controls[geo_col].dropna()))
    return test_regions, control_regions


def _power_date_strings(dataset, metric: str) -> tuple[str, ...]:
    frame = dataset.data[dataset.data["metric"].astype(str) == str(metric)]
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna().dt.normalize().unique()
    return tuple(sorted(pd.Timestamp(value).date().isoformat() for value in dates))


def _power_default_date(options: tuple[str, ...], preferred, fallback_index: int) -> str:
    if preferred:
        try:
            value = pd.Timestamp(preferred).date().isoformat()
        except (TypeError, ValueError):
            value = None
        if value in options:
            return value
    return options[min(max(fallback_index, 0), len(options) - 1)]


def _parse_float_list(value: str, label: str, *, percent: bool = False) -> tuple[float, ...]:
    try:
        parsed = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be comma-separated numbers") from exc
    if not parsed or any(not math.isfinite(item) for item in parsed):
        raise ValueError(f"{label} must contain at least one finite number")
    if percent:
        parsed = tuple(item / 100.0 for item in parsed)
    return parsed


def _parse_int_list(value: str, label: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"{label} must be comma-separated whole numbers") from exc
    if not parsed or any(item <= 0 for item in parsed):
        raise ValueError(f"{label} must contain positive whole numbers")
    return parsed


def _split_custom_list(value: str) -> list[str]:
    """Split an optional free-text "add custom values" field into raw tokens,
    to be joined with preset values and parsed by _parse_float_list/_parse_int_list."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_custom_weights(value: str) -> Mapping[str, float]:
    weights: dict[str, float] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError("Custom weights must use Region=weight pairs")
        region, raw_weight = (part.strip() for part in item.split("=", 1))
        try:
            weight = float(raw_weight)
        except ValueError as exc:
            raise ValueError(f"Custom weight for {region!r} is not numeric") from exc
        if not region or not math.isfinite(weight) or weight <= 0:
            raise ValueError("Custom weights must have non-empty regions and positive values")
        weights[region] = weight
    if not weights:
        raise ValueError("Enter at least one Region=weight pair for custom market size")
    return weights


def _market_size_options(dataset) -> tuple[MarketSizeMeasure, ...]:
    options = [MarketSizeMeasure.HISTORICAL_KPI_VOLUME, MarketSizeMeasure.CUSTOM_WEIGHT]
    population_weights = st.session_state.get("power_population_weights")
    regions = set(dataset.data["region"].astype(str))
    if population_weights and set(population_weights) == regions:
        options.insert(1, MarketSizeMeasure.POPULATION)
    return tuple(options)


def _market_size_label(value: MarketSizeMeasure) -> str:
    return {
        MarketSizeMeasure.HISTORICAL_KPI_VOLUME: "Historical KPI volume",
        MarketSizeMeasure.POPULATION: "Population",
        MarketSizeMeasure.CUSTOM_WEIGHT: "Custom regional weight",
    }[value]


def _render_selected_design_power(
    dataset,
    test_regions: tuple[str, ...],
    control_regions: tuple[str, ...],
    *,
    experiment_record_factory: ExperimentRecordFactory | None,
    save_experiment_record: ExperimentRecordSaver | None,
) -> None:
    st.markdown("### Selected-design production power")
    validation_inputs = st.session_state.get("experiment_validation_inputs") or {}
    validation_results = st.session_state.get("validation_results") or {}
    metric_options = tuple(str(value) for value in dataset.metrics)
    preferred_metric = str(validation_inputs.get("selected_metric") or metric_options[0])
    metric_index = (
        metric_options.index(preferred_metric) if preferred_metric in metric_options else 0
    )

    with st.form("production_power_form"):
        metric = st.selectbox(
            "Metric",
            metric_options,
            index=metric_index,
            help="Select the canonical KPI metric used by the production power calculation.",
        )
        date_options = _power_date_strings(dataset, metric)
        if len(date_options) < 2:
            st.warning(
                "At least two retained KPI dates are required to define history and a test period."
            )
            return
        preferred_end = validation_inputs.get("pre_end")
        preferred_start = validation_inputs.get("pre_start")
        history_end = st.selectbox(
            "Historical period end",
            date_options,
            index=date_options.index(
                _power_default_date(date_options, preferred_end, max(0, len(date_options) - 2))
            ),
            help="The last date included in the historical fitting period.",
        )
        end_index = date_options.index(history_end)
        history_start_options = date_options[: end_index + 1]
        history_start = st.selectbox(
            "Historical period start",
            history_start_options,
            index=history_start_options.index(
                _power_default_date(history_start_options, preferred_start, 0)
            ),
        )
        holdout_date_options = date_options[end_index + 1 :]
        preferred_test_start = validation_results.get("test_start") or validation_inputs.get(
            "test_start"
        )
        preferred_test_end = validation_results.get("test_end") or validation_inputs.get("test_end")
        default_test_dates = [
            value
            for value in holdout_date_options
            if preferred_test_start
            and preferred_test_end
            and pd.Timestamp(preferred_test_start).date().isoformat()
            <= value
            <= pd.Timestamp(preferred_test_end).date().isoformat()
        ]
        if not default_test_dates:
            default_test_dates = list(holdout_date_options[:1])
        historical_holdout_dates = st.multiselect(
            "Historical analytical holdout dates",
            holdout_date_options,
            default=default_test_dates,
            help="Source-backed dates used for power; these are not future campaign dates.",
        )
        planned_duration_periods = st.number_input(
            "Planned campaign duration (periods)",
            min_value=1,
            value=max(1, len(default_test_dates)),
            step=1,
            help="The historical holdout count must match the planned duration.",
        )
        preferred_frequency = str(validation_inputs.get("time_series_frequency") or "weekly")
        frequency = st.selectbox(
            "Frequency",
            ("weekly", "daily"),
            index=(
                ("weekly", "daily").index(preferred_frequency)
                if preferred_frequency in {"weekly", "daily"}
                else 0
            ),
            format_func=lambda value: value.title(),
        )
        schedule_known = st.checkbox(
            "Future campaign dates are known",
            value=False,
            help="Optional metadata only; future dates are never used as observations.",
        )
        holdout_last = (
            pd.Timestamp(historical_holdout_dates[-1])
            if historical_holdout_dates
            else pd.Timestamp(history_end)
        )
        schedule_step = pd.Timedelta(days=7 if frequency == "weekly" else 1)
        planned_start = st.date_input(
            "Planned campaign start date (used when schedule is known)",
            value=(holdout_last + schedule_step).date(),
            min_value=(holdout_last + schedule_step).date(),
        )
        direction = st.selectbox(
            "Effect direction",
            ("one_sided_positive", "one_sided_negative", "two_sided"),
            format_func=lambda value: value.replace("_", " ").title(),
        )
        effect_col, power_col = st.columns(2)
        with effect_col:
            target_effect = st.number_input(
                "Target effect (%)", min_value=0.0, value=10.0, step=1.0
            )
        with power_col:
            target_power = st.number_input(
                "Target power", min_value=0.50, max_value=0.99, value=0.80, step=0.05
            )
        with st.expander("Method details (advanced)", expanded=False):
            st.caption("Current defaults are the approved method; change only for expert review.")
            method_col, fit_col = st.columns(2)
            with method_col:
                method = st.selectbox(
                    "Simulation method", ("model_simulation", "residual_simulation")
                )
            with fit_col:
                fit_method = st.selectbox("Counterfactual fit", ("ols", "elastic_net", "lasso"))
            simulations_col, bound_col, history_col = st.columns(3)
            with simulations_col:
                n_simulations = st.number_input("Simulations", min_value=100, value=1000, step=100)
            with bound_col:
                mde_upper = st.number_input(
                    "MDE upper bound (%)", min_value=1.0, value=50.0, step=1.0
                )
            with history_col:
                min_history = st.number_input(
                    "Minimum historical periods", min_value=1, value=104, step=1
                )
        st.caption(
            f"Executed design: {len(test_regions)} test region(s), {len(control_regions)} control region(s)."
        )
        run_power = st.form_submit_button("▶ Run production power", type="primary")

    if run_power:
        if not historical_holdout_dates:
            st.error("Select at least one historical analytical holdout date.")
        elif len(historical_holdout_dates) != int(planned_duration_periods):
            st.error(
                "The historical analytical holdout must contain exactly the planned campaign duration in periods."
            )
        elif target_effect > mde_upper:
            st.error("Target effect must be within the MDE bounds.")
        else:
            config = ProductionPowerConfig(
                method=method,
                fit_method=fit_method,
                test_regions=test_regions,
                control_regions=control_regions,
                historical_start=pd.Timestamp(history_start),
                historical_end=pd.Timestamp(history_end),
                historical_holdout_dates=tuple(
                    pd.Timestamp(value) for value in historical_holdout_dates
                ),
                planned_duration_periods=int(planned_duration_periods),
                planned_test_dates=(
                    tuple(
                        pd.date_range(
                            pd.Timestamp(planned_start),
                            periods=int(planned_duration_periods),
                            freq="7D" if frequency == "weekly" else "D",
                        )
                    )
                    if schedule_known
                    else ()
                ),
                target_effects=(float(target_effect),),
                side=direction,
                frequency=frequency,
                target_power=float(target_power),
                n_simulations=int(n_simulations),
                mde_bounds=(0.0, float(mde_upper)),
                min_historical_periods=int(min_history),
                metric_value=metric,
            )
            record = experiment_record_factory() if experiment_record_factory else None
            try:
                with st.spinner("Running production power simulations..."):
                    result = run_production_power(dataset, config, experiment_record=record)
                st.session_state.production_power_config = config
                st.session_state.production_power_result = result
                if record is not None and save_experiment_record:
                    save_experiment_record(record)
                if result.completed:
                    st.success(
                        "Production power run completed and recorded in the experiment record."
                    )
                else:
                    st.warning(
                        "Production power run is incomplete or blocked; the result was recorded for audit and is not usable for recommendation."
                    )
            except (TypeError, ValueError, KeyError) as exc:
                st.error(f"Production power could not run: {exc}")

    result = st.session_state.get("production_power_result")
    config = st.session_state.get("production_power_config")
    if result is None or config is None:
        st.info(
            "No selected-design power result yet. Configure the explicit inputs above and run the analysis."
        )
        return
    try:
        stale = production_result_is_stale(result, dataset, config)
    except (TypeError, ValueError, KeyError):
        stale = True
    if stale:
        st.warning(
            "This production power result is stale because its dataset or explicit inputs changed. Re-run it before using it."
        )
    st.markdown("#### Selected-design result")
    result_cols = st.columns(4)
    result_cols[0].metric("Support status", result.support_status)
    result_cols[1].metric("MDE", f"{result.mde:.2f}%" if result.mde is not None else "Not reached")
    result_cols[2].metric(
        "Power at target",
        f"{result.power_at_target_effects[0]:.1%}"
        if result.power_at_target_effects
        else "Unavailable",
    )
    result_cols[3].metric("Effective test periods", result.effective_test_periods)
    for blocker in result.blockers:
        st.error(blocker)
    for warning in result.warnings:
        st.warning(warning)
    curve = pd.DataFrame(
        {
            "Effect size": result.effect_grid,
            "Power": result.power_curve,
            "Lower interval": result.power_ci_lower,
            "Upper interval": result.power_ci_upper,
        }
    )
    st.dataframe(curve, width="stretch", hide_index=True)
    st.line_chart(curve.set_index("Effect size")["Power"])
    st.download_button(
        "⬇ Download production power result (.json)",
        data=json.dumps(result.to_dict(), indent=2, default=str),
        file_name="production_power_result.json",
        mime="application/json",
        key="download_production_power_result",
    )


def _scenario_weights(measure: MarketSizeMeasure, dataset) -> Mapping[str, float] | None:
    if measure is MarketSizeMeasure.HISTORICAL_KPI_VOLUME:
        return None
    if measure is MarketSizeMeasure.POPULATION:
        weights = st.session_state.get("power_population_weights")
        if not weights:
            raise ValueError("Population weights are unavailable for the current geography source")
        return weights
    return _parse_custom_weights(st.session_state.get("power_custom_weights_input", ""))


def _render_scenario_results(result) -> None:
    selected = result.selected if result.objective is not None else None
    if selected is not None:
        st.success(
            f"**Recommended: {selected.actual_share:.1%} test share, "
            f"{selected.duration_periods} period(s).** This is the qualifying candidate "
            "under the selected objective."
        )
    elif any(candidate.recommendation_eligible for candidate in result.candidates):
        st.info("A qualifying candidate exists but no objective was set to select one.")
    else:
        _blocking_factors = sorted(
            {
                blocker
                for candidate in result.candidates
                for blocker in candidate.recommendation_blockers
            }
        )
        if _blocking_factors:
            st.warning(
                "**No candidate currently qualifies.** Limiting factor(s): "
                + "; ".join(_blocking_factors[:3])
            )
        else:
            st.info("No qualifying candidate identified yet.")

    rows = []
    for index, candidate in enumerate(result.candidates, start=1):
        power = candidate.power_result
        rows.append(
            {
                "Candidate": index,
                "Requested share": candidate.requested_share,
                "Achieved share": candidate.actual_share,
                "Market-size measure": _market_size_label(
                    MarketSizeMeasure(candidate.market_size_measure)
                ),
                "Duration": candidate.duration_periods,
                "Test regions": ", ".join(candidate.test_regions),
                "Control regions": ", ".join(candidate.control_regions),
                "Match": candidate.design_assessment.match_status,
                "Counterfactual": candidate.design_assessment.counterfactual_status,
                "MDE": power.mde if power else None,
                "Power at target": power.power_at_target_effects[0]
                if power and power.power_at_target_effects
                else None,
                "Power support": power.support_status if power else "not_run",
                "Qualifying": candidate.recommendation_eligible,
                "Limiting factor": "; ".join(candidate.recommendation_blockers),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    for index, candidate in enumerate(result.candidates, start=1):
        with st.expander(
            f"Candidate {index}: {candidate.actual_share:.1%} / {candidate.duration_periods} periods"
        ):
            st.write(
                {
                    "test_regions": candidate.test_regions,
                    "control_regions": candidate.control_regions,
                }
            )
            st.json(
                {
                    "design_assessment": {
                        "match_status": candidate.design_assessment.match_status,
                        "counterfactual_status": candidate.design_assessment.counterfactual_status,
                        "match_metrics": candidate.design_assessment.match_metrics,
                        "counterfactual_metrics": candidate.design_assessment.counterfactual_metrics,
                        "warnings": candidate.design_assessment.warnings,
                        "blockers": candidate.design_assessment.blockers,
                        "matching_method": candidate.design_assessment.matching_method,
                        "matching_seed": candidate.design_assessment.matching_seed,
                        "validation_method": candidate.design_assessment.validation_method,
                        "control_selection_provenance": candidate.design_assessment.control_selection_provenance,
                    },
                    "recommendation_blockers": candidate.recommendation_blockers,
                }
            )
            if candidate.power_result:
                power = candidate.power_result
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Effect size": power.effect_grid,
                            "Power": power.power_curve,
                            "Lower interval": power.power_ci_lower,
                            "Upper interval": power.power_ci_upper,
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    f"Input fingerprint: {power.input_fingerprint} · source fingerprint: {power.source_data_fingerprint}"
                )
                for blocker in power.blockers:
                    st.error(blocker)
                for warning in power.warnings:
                    st.warning(warning)


def _render_scenario_comparison(dataset) -> None:
    st.markdown("### Compare candidate test-size and duration scenarios")
    st.caption(
        "Compare explicit market shares and durations using the canonical KPI dataset. A candidate is not qualifying unless matching, historical validation and production power all support it."
    )
    metric_options = tuple(str(value) for value in dataset.metrics)
    regions = tuple(sorted(set(dataset.data["region"].astype(str))))
    market_options = _market_size_options(dataset)
    _common_shares = (10, 20, 30, 40, 50)
    _common_durations = (2, 4, 6, 8, 12)
    _objective_choices = {
        "Find the smallest viable design": "smallest_test_share_then_duration",
        "Find the shortest viable duration": "shortest_duration_then_test_share",
    }
    with st.form("power_scenario_form"):
        metric = st.selectbox("Scenario metric", metric_options)
        date_options = _power_date_strings(dataset, metric)
        market_measure = st.selectbox(
            "Market-size measure", market_options, format_func=_market_size_label
        )
        objective_choice = st.selectbox(
            "Objective",
            list(_objective_choices),
            help="Which qualifying candidate to highlight as the recommended scenario.",
        )
        share_presets = st.multiselect(
            "Target test shares (%)", _common_shares, default=list(_common_shares)
        )
        custom_shares_text = st.text_input(
            "Add custom test shares (%, comma-separated, optional)", value=""
        )
        lock_duration = st.checkbox(
            "Lock duration",
            value=True,
            help="Use one business-fixed duration rather than comparing all duration values.",
        )
        if lock_duration:
            fixed_duration = st.number_input(
                "Fixed duration (periods)", min_value=1, value=4, step=1
            )
            duration_presets: tuple[int, ...] = ()
            custom_durations_text = ""
        else:
            fixed_duration = 0
            duration_presets = st.multiselect("Durations (periods)", _common_durations, default=[4])
            custom_durations_text = st.text_input(
                "Add custom durations (periods, comma-separated, optional)", value=""
            )
        target_effects_text = st.text_input("Target effects (%)", value="5, 10")
        target_power = st.number_input(
            "Scenario target power", min_value=0.50, max_value=0.99, value=0.80, step=0.05
        )
        frequency = st.selectbox(
            "Scenario frequency",
            ("weekly", "daily"),
            index=0,
            format_func=lambda value: value.title(),
        )
        with st.expander("Method details (advanced)", expanded=False):
            st.caption("Current defaults are the approved method; change only for expert review.")
            method_col, fit_col = st.columns(2)
            with method_col:
                method = st.selectbox(
                    "Scenario simulation method", ("model_simulation", "residual_simulation")
                )
            with fit_col:
                fit_method = st.selectbox(
                    "Scenario counterfactual fit", ("ols", "elastic_net", "lasso")
                )
            mde_upper = st.number_input(
                "Scenario MDE upper bound (%)", min_value=1.0, value=50.0, step=1.0
            )
            n_simulations = st.number_input(
                "Scenario simulations per candidate", min_value=100, value=1000, step=100
            )
            matching_strategy = st.selectbox(
                "Candidate matching strategy", ("basic", "intermediate", "stochastic"), index=1
            )
            random_seed = st.number_input("Scenario random seed", min_value=0, value=42, step=1)
        with st.expander("Region constraints (advanced)", expanded=False):
            force_test = st.multiselect("Force test regions", regions)
            force_control = st.multiselect("Force control regions", regions)
            exclude_both = st.multiselect("Exclude from both groups", regions)
            test_only_exclude = st.multiselect("Exclude from test", regions)
            control_only_exclude = st.multiselect("Exclude from control", regions)
        custom_weights_input = ""
        if market_measure is MarketSizeMeasure.CUSTOM_WEIGHT:
            custom_weights_input = st.text_input(
                "Custom regional weights (Region=weight, comma-separated)"
            )
        end_default = max(0, len(date_options) - (int(fixed_duration) if lock_duration else 4) - 1)
        history_end = st.selectbox(
            "Scenario historical period end", date_options, index=end_default
        )
        end_index = date_options.index(history_end)
        history_start = st.selectbox(
            "Scenario historical period start", date_options[: end_index + 1], index=0
        )
        run_scenarios = st.form_submit_button("▶ Compare candidate scenarios", type="primary")

    if not run_scenarios:
        previous = st.session_state.get("power_scenario_result")
        if previous is not None:
            _render_scenario_results(previous)
        return
    try:
        target_shares_text = ", ".join(
            [str(value) for value in share_presets] + _split_custom_list(custom_shares_text)
        )
        durations = (
            (int(fixed_duration),)
            if lock_duration
            else _parse_int_list(
                ", ".join(
                    [str(value) for value in duration_presets]
                    + _split_custom_list(custom_durations_text)
                ),
                "Durations",
            )
        )
        target_shares = _parse_float_list(target_shares_text, "Target test shares", percent=True)
        target_effects = _parse_float_list(target_effects_text, "Target effects")
        if any(effect < 0 for effect in target_effects):
            raise ValueError("Target effects must be non-negative")
        holdout_dates = tuple(pd.Timestamp(value) for value in date_options[end_index + 1 :])
        if not holdout_dates:
            raise ValueError(
                "Select a historical end date with source-backed dates after it for the analytical holdout"
            )
        base_duration = durations[0]
        if len(holdout_dates) < base_duration:
            raise ValueError(
                f"Only {len(holdout_dates)} source-backed holdout dates follow the selected history; choose a shorter duration or earlier history end"
            )
        if market_measure is MarketSizeMeasure.CUSTOM_WEIGHT:
            regional_weights = _parse_custom_weights(custom_weights_input)
        else:
            regional_weights = _scenario_weights(market_measure, dataset)
        template = ProductionPowerConfig(
            method=method,
            fit_method=fit_method,
            test_regions=(regions[0],),
            control_regions=(regions[1],) if len(regions) > 1 else (),
            historical_start=pd.Timestamp(history_start),
            historical_end=pd.Timestamp(history_end),
            historical_holdout_dates=holdout_dates[:base_duration],
            planned_duration_periods=base_duration,
            target_effects=target_effects,
            frequency=frequency,
            target_power=float(target_power),
            n_simulations=int(n_simulations),
            mde_bounds=(0.0, float(mde_upper)),
            min_historical_periods=104 if frequency == "weekly" else 84,
            metric_value=metric,
        )
        constraints = MatchConstraints(
            force_test_include=tuple(force_test),
            force_control_include=tuple(force_control),
            exclude_from_both=tuple(exclude_both),
            test_only_exclude=tuple(test_only_exclude),
            control_only_exclude=tuple(control_only_exclude),
        )
        config = ScenarioSizingConfig(
            target_shares=target_shares,
            durations=durations,
            historical_end=pd.Timestamp(history_end),
            metric_value=metric,
            market_size_measure=market_measure,
            regional_weights=regional_weights,
            constraints=constraints,
            share_tolerance=0.05,
            random_seed=int(random_seed),
            power_template=template,
            frequency=frequency,
            matching_strategy=matching_strategy,
            validation_method="enet",
            objective=_objective_choices[objective_choice],
        )
        with st.spinner("Building, validating and sizing candidate scenarios..."):
            result = size_power_scenarios(dataset, config)
        st.session_state.power_scenario_config = config
        st.session_state.power_scenario_result = result
        st.success(f"Compared {len(result.candidates)} candidate scenario(s).")
        _render_scenario_results(result)
    except (TypeError, ValueError, KeyError) as exc:
        st.error(f"Scenario comparison could not run: {exc}")


def render_power_test_sizing_tab(
    *,
    experiment_record_factory: ExperimentRecordFactory | None = None,
    save_experiment_record: ExperimentRecordSaver | None = None,
) -> None:
    """Render selected-design power and the candidate scenario comparison workflow."""

    st.subheader("📈 Power Analysis & Test Sizing")
    st.caption(
        "Statistical detectability is separate from media delivery and effect plausibility. Use the candidate comparison to inspect real matched and historically validated designs."
    )
    dataset = st.session_state.get("kpi_regional_dataset")
    if dataset is None:
        st.info(
            "Prepare a canonical KPI dataset in **Validate Test Design** first. The power workflows reuse that exact source and provenance fingerprint."
        )
        return
    test_regions, control_regions = _power_region_groups()
    if test_regions and control_regions:
        _render_selected_design_power(
            dataset,
            test_regions,
            control_regions,
            experiment_record_factory=experiment_record_factory,
            save_experiment_record=save_experiment_record,
        )
    else:
        st.info(
            "No executed test/control design is available for selected-design power. Candidate scenario comparison can still construct designs from the canonical dataset."
        )
    _render_scenario_comparison(dataset)
