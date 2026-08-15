"""Deterministic end-to-end prospective planning fixture.

The fixture deliberately contains more than two identifier columns so the
workflow must make an explicit aggregation and metric selection before the
canonical regional KPI contract is built.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from geotestlab.data import MarketSizeMeasure, RegionalKPIConfig, prepare_regional_kpi
from geotestlab.effect.plausibility import (
    EffectEvidence,
    EffectScenario,
    EvidenceQuality,
    EvidenceType,
    assess_effect_plausibility,
)
from geotestlab.experiment import (
    build_experiment_export,
    build_unified_result_summaries,
    compute_input_fingerprint,
    create_experiment_record,
    freeze_design,
    propagate_staleness,
    record_stage_result,
    update_inputs,
)
from geotestlab.experiment.content import sha256_bytes
from geotestlab.matching import MatchConfig
from geotestlab.media.delivery import (
    DeliveryThresholds,
    ExperimentMediaScope,
    assess_media_delivery,
)
from geotestlab.media.profiles import InputProvenance, MediaPlan, MediaValue
from geotestlab.power.production import ProductionPowerConfig, run_production_power
from geotestlab.power.scenarios import ScenarioSizingConfig, size_power_scenarios
from geotestlab.recommendation import (
    DesignScenario,
    RecommendationObjective,
    assess_design_recommendation,
)

END_TO_END_REGIONS = ("Region A", "Region B", "Region C", "Region D", "Region E", "Region F")
END_TO_END_METRIC = "Sales"
END_TO_END_FREQUENCY = "weekly"
END_TO_END_PERIODS = 108
END_TO_END_HISTORICAL_PERIODS = 104
END_TO_END_DURATION = 4


def write_end_to_end_kpi_xlsx(path: str | Path) -> Path:
    """Write a stable aggregated KPI workbook with correlated regional series."""

    rng = np.random.default_rng(2026)
    dates = pd.date_range("2024-01-07", periods=END_TO_END_PERIODS, freq="7D")
    trend = np.arange(END_TO_END_PERIODS, dtype=float)
    common_pattern = 100.0 + 7.0 * np.sin(trend / 5.0) + 0.1 * trend
    rows: list[dict] = []
    for region in END_TO_END_REGIONS:
        # Two raw rows per region force the explicit aggregation step while
        # preserving a stable, near-identical regional historical pattern.
        noise = rng.normal(0.0, 0.5, size=END_TO_END_PERIODS)
        for store_index in range(2):
            values = (common_pattern + noise) / 2.0
            rows.append(
                {
                    "Store ID": f"{region}-store-{store_index}",
                    "TV Region": region,
                    "Sub-Region": f"{region} sub",
                    "Metric": END_TO_END_METRIC,
                    **{date: float(value) for date, value in zip(dates, values, strict=True)},
                }
            )

    output = Path(path)
    pd.DataFrame(rows).to_excel(output, index=False, engine="openpyxl")
    return output


def load_end_to_end_dataset(path: str | Path):
    """Read the fixture and apply explicit aggregation/metric selections."""

    raw = pd.read_excel(path, engine="openpyxl")
    config = RegionalKPIConfig(
        aggregation_column="TV Region",
        metric_column="Metric",
        metric_value=END_TO_END_METRIC,
        market_size_measure=MarketSizeMeasure.HISTORICAL_KPI_VOLUME,
    )
    return prepare_regional_kpi(raw, config)


def _power_template(dataset) -> ProductionPowerConfig:
    dates = tuple(sorted(pd.to_datetime(dataset.data["date"]).dt.normalize().unique()))
    historical_end = pd.Timestamp(dates[END_TO_END_HISTORICAL_PERIODS - 1])
    holdout_dates = tuple(pd.Timestamp(value) for value in dates[END_TO_END_HISTORICAL_PERIODS:])
    future_dates = tuple(
        pd.date_range(
            holdout_dates[-1] + pd.Timedelta(days=7),
            periods=END_TO_END_DURATION,
            freq="7D",
        )
    )
    return ProductionPowerConfig(
        method="model_simulation",
        fit_method="ols",
        test_regions=(END_TO_END_REGIONS[0],),
        control_regions=(END_TO_END_REGIONS[1],),
        historical_start=pd.Timestamp(dates[0]),
        historical_end=historical_end,
        historical_holdout_dates=holdout_dates,
        planned_duration_periods=END_TO_END_DURATION,
        planned_test_dates=future_dates,
        target_effects=(5.0,),
        effect_grid=(0.0, 5.0, 10.0, 20.0),
        mde_bounds=(0.0, 20.0),
        n_simulations=100,
        random_seed=7,
        min_historical_periods=END_TO_END_HISTORICAL_PERIODS,
        min_placebo_windows=5,
        metric_value=END_TO_END_METRIC,
    )


def _media_assessment():
    forecast = lambda value, source: MediaValue(  # noqa: E731
        value,
        InputProvenance.SUPPLIED_FORECAST,
        source=source,
        source_date="2026-01-01",
    )
    plan = MediaPlan(
        profile_id="meta_auction_social",
        values={
            "total_budget": forecast(5000.0, "Meta Ads Manager forecast"),
            "cpm": forecast(10.0, "Meta Ads Manager forecast"),
            "frequency": forecast(2.0, "Meta Ads Manager forecast"),
            "eligible_audience": forecast(1_000_000.0, "Meta Ads Manager forecast"),
            "campaign_objective": MediaValue(
                "conversions", InputProvenance.ANALYST_ASSUMPTION, source="fixture"
            ),
        },
    )
    thresholds = DeliveryThresholds(min_impressions=400_000, min_reach_percentage=20)
    scope = ExperimentMediaScope(excluded_from_experiment=(END_TO_END_REGIONS[-1],))
    result = assess_media_delivery(plan, thresholds, scope)
    assert result.status.value == "feasible"
    return plan, thresholds, scope, result


def _effect_assessment(mde: float | None, delivery) -> EffectEvidence:
    evidence = EffectEvidence(
        evidence_type=EvidenceType.PRIOR_SAME_MARKET_PLATFORM_GEO_TEST,
        quality=EvidenceQuality.HIGH,
        source="deterministic prior Meta geo-test fixture",
        source_date="2025-12-01",
        scenarios=(
            EffectScenario("low", 3.0),
            EffectScenario("central", 5.0),
            EffectScenario("high", 8.0),
        ),
        central_approved=True,
    )
    result = assess_effect_plausibility(
        evidence,
        mde_pct=mde,
        effect_direction="one_sided_positive",
        delivery_status=delivery.status.value,
        delivery_fingerprint=delivery.input_fingerprint,
    )
    assert result.status.value == "evidence_backed"
    return evidence, result


def _recommendation_scenarios(sizing, delivery, effect, source_fingerprint):
    scenarios = []
    for index, candidate in enumerate(sizing.candidates, start=1):
        power = candidate.power_result
        assert power is not None
        central = next(item for item in effect.comparisons if item.label == "central")
        scenarios.append(
            DesignScenario(
                scenario_id=f"fixture-candidate-{index}",
                size_metric=candidate.actual_share,
                duration_periods=candidate.duration_periods,
                cost=float(delivery.values["total_budget"].value),
                match_status=candidate.design_assessment.match_status,
                counterfactual_status=candidate.design_assessment.counterfactual_status,
                power_status=power.support_status,
                power_usable=power.usable_for_recommendation,
                power_meets_target=all(
                    value >= power.target_power for value in power.power_at_target_effects
                ),
                delivery_status=delivery.status.value,
                effect_status=effect.status.value,
                effect_meets_mde=central.meets_mde,
                region_constraints_status="pass",
                history_periods=power.historical_data_sufficiency.get("retained_periods"),
                metadata={
                    "source": "scenario_sizing_result",
                    "analyst_supplied": False,
                    "market_size_measure": candidate.market_size_measure,
                    "source_data_fingerprint": source_fingerprint,
                    "test_regions": list(candidate.test_regions),
                    "control_regions": list(candidate.control_regions),
                    "power_input_fingerprint": power.input_fingerprint,
                },
            )
        )
    return tuple(scenarios)


def run_end_to_end_planning(path: str | Path) -> dict:
    """Run the complete deterministic planning contract and return artefacts."""

    dataset = load_end_to_end_dataset(path)
    assert dataset.config.aggregation_column == "TV Region"
    assert dataset.config.metric_value == END_TO_END_METRIC
    power_template = _power_template(dataset)
    sizing = size_power_scenarios(
        dataset,
        ScenarioSizingConfig(
            target_shares=(1 / 6, 2 / 6),
            durations=(END_TO_END_DURATION,),
            historical_end=power_template.historical_end,
            metric_value=END_TO_END_METRIC,
            market_size_measure=MarketSizeMeasure.HISTORICAL_KPI_VOLUME,
            share_tolerance=0.05,
            matching_strategy="intermediate",
            validation_method="enet",
            match_config=MatchConfig(smd_high_threshold=2.0),
            power_template=power_template,
            objective="smallest_test_share_then_duration",
        ),
    )
    assert len(sizing.candidates) == 2
    assert all(candidate.control_regions for candidate in sizing.candidates)
    assert all(
        candidate.design_assessment.counterfactual_status == "pass"
        for candidate in sizing.candidates
    )
    assert all(candidate.power_result is not None for candidate in sizing.candidates)
    assert all(candidate.recommendation_eligible for candidate in sizing.candidates)
    assert all(candidate.planned_test_dates for candidate in sizing.candidates)
    source_dates = set(pd.to_datetime(dataset.data["date"]).dt.normalize())
    assert set(pd.to_datetime(power_template.planned_test_dates)).isdisjoint(source_dates)

    selected = sizing.selected_candidate
    assert selected is not None
    plan, thresholds, scope, delivery = _media_assessment()
    evidence, effect = _effect_assessment(selected.power_result.mde, delivery)
    recommendation_scenarios = _recommendation_scenarios(
        sizing, delivery, effect, dataset.source_data_fingerprint
    )
    recommendation = assess_design_recommendation(
        recommendation_scenarios,
        RecommendationObjective.SMALLEST_QUALIFYING_DESIGN,
    )
    assert recommendation.status.value == "recommended"
    assert recommendation.selected_scenario_id == "fixture-candidate-1"

    record = create_experiment_record(datetime(2026, 1, 1, tzinfo=UTC))
    matching_fingerprint = compute_input_fingerprint(
        {
            "source_data_fingerprint": dataset.source_data_fingerprint,
            "candidate": selected.test_regions,
        }
    )
    validation_fingerprint = compute_input_fingerprint(
        {
            "matching": matching_fingerprint,
            "assessment": selected.design_assessment.counterfactual_metrics,
        }
    )
    record.content_digests = {"source_bytes": sha256_bytes(Path(path).read_bytes())}
    update_inputs(
        record,
        compute_input_fingerprint(
            {
                "source_data_fingerprint": dataset.source_data_fingerprint,
                "duration": END_TO_END_DURATION,
            }
        ),
        {
            "kpi_file_name": Path(path).name,
            "selected_metric": END_TO_END_METRIC,
            "kpi_agg_col": "TV Region",
            "time_series_frequency": END_TO_END_FREQUENCY,
        },
    )
    record_stage_result(record, "match_quality", matching_fingerprint)
    record_stage_result(record, "counterfactual_validation", validation_fingerprint)
    record_stage_result(record, "statistical_power", selected.power_result.input_fingerprint)
    record_stage_result(record, "media_delivery", delivery.input_fingerprint)
    record_stage_result(record, "effect_plausibility", effect.input_fingerprint)

    planned = {
        "pre_start": power_template.historical_start.isoformat(),
        "pre_end": power_template.historical_end.isoformat(),
        "test_start": power_template.planned_test_dates[0].isoformat(),
        "test_end": power_template.planned_test_dates[-1].isoformat(),
        "use_post": False,
        "planned_test_periods": END_TO_END_DURATION,
        "analysed_test_periods": None,
        "excluded_test_periods": None,
        "time_series_frequency": END_TO_END_FREQUENCY,
    }
    design = {
        "experiment_identity": {"experiment_id": record.experiment_id},
        "matching": {
            "market": "Synthetic Meta planning fixture",
            "geography_level": "TV Region",
            "test_regions": list(selected.test_regions),
            "control_regions": list(selected.control_regions),
            "matching_method": selected.design_assessment.matching_method,
            "matching_seed": selected.design_assessment.matching_seed,
            "market_size_measure": selected.market_size_measure,
            "requested_test_share": selected.requested_share,
            "achieved_test_share": selected.actual_share,
        },
        "validation": selected.design_assessment.counterfactual_metrics,
        "power": {"config": power_template.to_dict(), "result": selected.power_result.to_dict()},
        "media_delivery": {
            "plan": plan.to_dict(),
            "thresholds": thresholds.to_dict(),
            "scope": scope.to_dict(),
            "result": delivery.to_dict(),
        },
        "effect_plausibility": effect.to_dict(),
        "effect_evidence": evidence.to_dict(),
        "recommendation": recommendation.to_dict(),
        "recommendation_scenarios": [item.to_dict() for item in recommendation_scenarios],
        "source_data_fingerprint": dataset.source_data_fingerprint,
        "methodology_version": selected.power_result.methodology_version,
        "planned_campaign_dates": [
            value.isoformat() for value in power_template.planned_test_dates
        ],
    }
    frozen_v1 = freeze_design(
        record,
        planned,
        record.input_fingerprint,
        label="Synthetic Meta design v1",
        design=design,
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )
    summaries = build_unified_result_summaries(
        validation_results={
            "results": {"candidate": selected.design_assessment.counterfactual_metrics}
        },
        power_result=selected.power_result,
        power_config=power_template,
        media_delivery_result=delivery,
        media_delivery_plan=plan,
        media_delivery_thresholds=thresholds,
        media_delivery_scope=scope,
        effect_plausibility_result=effect,
        recommendation_result=recommendation,
        recommendation_scenarios=recommendation_scenarios,
        recommendation_objective=RecommendationObjective.SMALLEST_QUALIFYING_DESIGN,
    )
    export = build_experiment_export(record, result_summaries=summaries)
    assert export["active_frozen_design"]["version"] == 1
    assert export["result_summaries"]["statistical_power"]["planned_test_dates"]

    original_fingerprints = dict(record.stage_fingerprints)
    changed_current = {
        stage: f"changed:{fingerprint}" for stage, fingerprint in original_fingerprints.items()
    }
    changed_stages = propagate_staleness(record, changed_current)
    assert set(changed_stages) == set(original_fingerprints)
    assert all(record.stage_status[stage] == "stale" for stage in original_fingerprints)

    changed_power_config = replace(
        power_template,
        target_effects=(6.0,),
        effect_grid=(0.0, 6.0, 12.0, 20.0),
    )
    changed_power = run_production_power(
        dataset,
        replace(
            changed_power_config,
            test_regions=selected.test_regions,
            control_regions=selected.control_regions,
        ),
    )
    changed_effect_evidence, changed_effect = _effect_assessment(changed_power.mde, delivery)
    changed_scenario = DesignScenario(
        **{
            **recommendation_scenarios[0].__dict__,
            "power_status": changed_power.support_status,
            "power_usable": changed_power.usable_for_recommendation,
            "power_meets_target": all(
                value >= changed_power.target_power
                for value in changed_power.power_at_target_effects
            ),
            "effect_status": changed_effect.status.value,
            "effect_meets_mde": next(
                item for item in changed_effect.comparisons if item.label == "central"
            ).meets_mde,
        }
    )
    changed_recommendation = assess_design_recommendation(
        [changed_scenario], RecommendationObjective.SMALLEST_QUALIFYING_DESIGN
    )
    assert changed_recommendation.status.value == "recommended"
    record_stage_result(
        record,
        "match_quality",
        compute_input_fingerprint({"revision": 2, "source": dataset.source_data_fingerprint}),
    )
    record_stage_result(
        record,
        "counterfactual_validation",
        compute_input_fingerprint({"revision": 2, "matching": selected.control_regions}),
    )
    record_stage_result(record, "statistical_power", changed_power.input_fingerprint)
    record_stage_result(record, "media_delivery", delivery.input_fingerprint)
    record_stage_result(record, "effect_plausibility", changed_effect.input_fingerprint)
    record.input_fingerprint = compute_input_fingerprint(
        {"revision": 2, "power": changed_power.input_fingerprint}
    )
    frozen_v2 = freeze_design(
        record,
        planned,
        record.input_fingerprint,
        label="Synthetic Meta design v2 after power-input change",
        design={
            **copy.deepcopy(design),
            "power": {"config": changed_power_config.to_dict(), "result": changed_power.to_dict()},
            "effect_plausibility": changed_effect.to_dict(),
            "recommendation": changed_recommendation.to_dict(),
            "effect_evidence": changed_effect_evidence.to_dict(),
        },
        now=datetime(2026, 1, 3, tzinfo=UTC),
    )
    assert frozen_v2["version"] == 2
    assert record.frozen_versions[0].to_dict()["label"] == "Synthetic Meta design v1"
    return {
        "dataset": dataset,
        "power_template": power_template,
        "sizing": sizing,
        "delivery": delivery,
        "effect": effect,
        "recommendation": recommendation,
        "record": record,
        "export": export,
    }
