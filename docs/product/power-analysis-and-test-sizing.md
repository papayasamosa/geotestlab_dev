# GeoTestLab Power Analysis and Test Sizing Specification

**Document type:** Functional and methodological product specification  
**Parent document:** `PRD.md`  
**Version:** 1.1
**Status:** Approved methodology; selected-design production implementation
delivered, with prospective-horizon, candidate-pipeline and broader
candidate-grid/duration UX in progress
**Date:** 15 August 2026

## 1. Purpose

This specification defines the prospective power-analysis and test-sizing capability required within GeoTestLab.

The methodology decision pack is approved under
[`ADR-000`](decisions/ADR-000-power-methodology-approval-gate.md). Approval
does not turn the experimental evidence harness into a production engine: the
production contract must preserve the approved method/support conditions and
must keep media-delivery and effect-plausibility assumptions outside the
statistical calculation.

## 1.1 Production statistical-power contract (PR4)

The first production boundary is implemented in
`geotestlab/power/production/`. It accepts a canonical `RegionalKPIDataset`
and an explicit `ProductionPowerConfig` containing the metric, historical
period, test/control regions, planned test dates, target effects, direction,
simulation method, fit method and approved simulation settings.

The current contract still uses the configured test dates as the analytical
simulation/holdout window and therefore requires those dates to be represented
in the source dataset. This is not a valid prospective contract when the
campaign is genuinely in the future. The next implementation stage must split
future campaign metadata (`planned_test_dates` and planned duration) from the
historical calibration/holdout horizon, preserve both in the result/export and
keep the existing history, continuity and safety gates.

It returns a typed `ProductionPowerResult` containing the power curve and
target-effect estimates, conditional Clopper–Pearson intervals, MDE, effective
and requested periods, fit and safety diagnostics, source/input fingerprints,
support status, blockers and warnings. It records the statistical-power stage
in the shared experiment record and can identify stale results when the source
dataset or configuration changes.

There is intentionally no implicit best-method default. `model_simulation` or
`residual_simulation` must be selected and recorded explicitly; empirical
placebo results remain a cross-check. The result is not a media feasibility or
effect-plausibility recommendation.

The scenario boundary in `geotestlab/power/scenarios.py` provides candidate
test-share and duration construction using explicit historical-KPI, population
or custom regional weights. It retains requested versus achieved share and
applies shared constraints, but the current candidate path does not yet
guarantee a newly matched control group and complete historical validation for
every candidate. Automatic recommendation must wait for that design-builder /
control-selector seam.

The **Power & Test Sizing** app tab exposes the selected-design production
power contract after canonical KPI preparation and executed matching. It
requires explicit method, counterfactual fit, effect direction, history, test
dates, target effect, power target and simulation settings. Results show the
support status, MDE, target power, curve table/chart and a JSON export; source
and input fingerprints remain attached to the experiment record. The tab does
not yet expose the full scenario grid, fixed-duration workflow or complete
upstream candidate pipeline, and it does not combine statistical detectability
with media delivery or effect plausibility.

The capability must help an analyst answer:

1. Are the selected test and control regions historically credible?
2. What effect can this design detect over the planned duration?
3. What test-market share or duration is required to detect the target effect?
4. Can the available budget deliver sufficient exposure within that test area?
5. Where effectiveness evidence exists, is the expected KPI effect at least as large as the minimum detectable effect?
6. If the design is not feasible, what is the limiting factor?

## 2. Conceptual model

The feature shall separate four layers.

### 2.1 Design quality

Whether test and control regions are structurally sensible and historically predictive.

### 2.2 Statistical detectability

Whether the regional design, historical noise, duration and target effect produce sufficient statistical power.

### 2.3 Media delivery feasibility

Whether budget and platform delivery can create the intended exposure within the proposed test regions.

### 2.4 Effect plausibility

Whether an explicit effectiveness estimate translates that exposure into an expected KPI effect that exceeds the minimum detectable effect.

These layers shall never be collapsed into one unexplained score.

## 3. Analysis modes

The user shall be able to run three levels of analysis.

### Mode A. Detectability only

Required inputs:

- selected test and control regions;
- historical KPI data;
- target uplift or desired minimum detectable effect;
- planned duration;
- desired power.

Outputs:

- estimated power;
- minimum detectable effect;
- required test size or duration scenarios.

### Mode B. Detectability plus delivery feasibility

Adds:

- platform;
- budget;
- audience and delivery forecasts;
- delivery thresholds.

Outputs:

- detectability status;
- delivery status;
- no conclusion about expected KPI effect unless an effectiveness bridge is supplied.

### Mode C. Full spend-sufficiency scenario

Adds:

- effectiveness evidence or explicit low, central and high assumptions.

Outputs:

- expected incremental KPI;
- expected uplift range;
- comparison with minimum detectable effect;
- conditional conclusion on whether spend is likely to produce a detectable effect.

## 4. Workflow placement

The feature shall appear after a proposed regional design has been generated and historical counterfactual validation has been completed.

Recommended sequence:

1. build candidate test and control groups;
2. validate historical match;
3. select candidate design;
4. run power analysis;
5. configure platform and budget;
6. enter or upload delivery forecasts;
7. add effectiveness evidence where available;
8. compare scenarios;
9. approve and freeze design.

A user may access detectability-only analysis before final media forecasts are available.

## 5. Inputs

### 5.0 Canonical regional KPI source contract

The historical KPI workbook is prepared once into a typed
`RegionalKPIDataset` shared by KPI Pattern matching, historical validation and
future power/test-sizing code. The contract supports both existing layouts:

- simple: `Region | Metric | date columns`;
- aggregated: `Raw Key | one or more classification/aggregation columns | Metric | date columns`.

For aggregated files the analyst selects the aggregation column used as the
experiment region, the metric column and, where needed, the metric value. The
preparation contract then:

- coerces KPI cells to numeric without replacing missing values with zero;
- aggregates all contributing raw rows by `(region, metric, date)` using
  `sum(min_count=1)`;
- reports blank classifications, non-numeric or missing cells, missing dates
  and duplicate analytical keys before modelling;
- retains raw-to-regional provenance, a source-data fingerprint and quality
  metadata; and
- exposes canonical long-form fields `region`, `date`, `metric`, `kpi`,
  `selected_aggregation` and `source_data_fingerprint`.

The dataset may contain multiple metrics and can be restricted to the selected
metric through a typed adapter. Existing KPI Pattern output that uses the
compatibility column `Population` to hold historical KPI volume is not a
production population measure. New sizing code must use an explicit
`market_size_measure` such as `historical_kpi_volume`, `population` or an
explicit custom weight; it must never infer market share from the number of
regions.

## 5.1 Experiment definition

Required:

- market;
- geography level;
- KPI;
- KPI frequency;
- historical period;
- selected test regions;
- selected control regions or control-selection method;
- excluded regions;
- planned test duration;
- planned test dates, where known, as future campaign metadata;
- a separate historical calibration/holdout horizon for power estimation.

The campaign dates and analytical horizon must never be conflated. A future
campaign may have no KPI observations yet; the power calculation must use a
defensible historical window selected from the available source history and
must export that distinction.

## 5.2 Statistical assumptions

Required:

- target uplift or request to calculate minimum detectable effect;
- desired power, default 80 percent;
- significance or decision threshold required by the approved method;
- positive, negative or two-sided effect direction;
- number of simulations, where applicable;
- random seed;
- effect start and shape.

Optional:

- ramp-up;
- delayed effect;
- carryover;
- varying effect by period;
- alternative noise-resampling policy.

## 5.3 Regional market-size measure

The user shall select one measure:

- population;
- customers;
- historical KPI volume;
- historical sign-up share;
- revenue;
- addressable audience;
- custom uploaded weight.

This measure determines the actual market share represented by candidate region sets.

## 5.4 Candidate design scenarios

Defaults should include candidate test shares such as:

- 10 percent;
- 20 percent;
- 30 percent;
- 40 percent;
- 50 percent.

The user can add, remove or edit percentages.

Candidate durations may include:

- 2 weeks;
- 4 weeks;
- 6 weeks;
- 8 weeks;
- 12 weeks.

The user can lock duration when the business brief fixes it.

Candidate uplifts may include:

- 2 percent;
- 5 percent;
- 10 percent;
- custom values.

## 6. Candidate-region construction

### TS-FR1. Market-share construction

Candidate groups shall be based on the selected market-size measure rather than the number of regions.

#### Acceptance criteria

- Requested share and actual achieved share are shown separately.
- Actual share is displayed to at least one decimal place.
- Unrounded values are retained for calculations and export.
- Constituent regions are displayed.
- Include and exclude constraints are respected.
- The difference from target share is shown.
- The product reports when indivisible regions prevent a close match.

### TS-FR2. Region constraints

Supported controls:

- force include in test;
- exclude from test;
- force control eligibility;
- exclude from control;
- exclude from both;
- lock existing test group;
- lock existing control group.

### TS-FR3. Match integration

Each candidate scenario shall retain or calculate:

- structural balance;
- KPI-pattern distance where used;
- pre-period validation metrics;
- Counterfactual Confidence;
- contamination or operational notes.

A candidate that fails minimum design-quality criteria cannot be recommended solely because its power is high.

## 7. Power-analysis engine

### PA-FR1. Design-specific power

Power must be estimated using the selected regional design and historical KPI behaviour.

A generic sample-size formula that ignores the chosen controls is insufficient as the primary method.

### PA-FR2. Method alignment

The power method should align with the intended evaluation method where feasible.

Potential first-release methods include:

- historical residual simulation;
- effect injection into held-out historical windows;
- model-based counterfactual simulation;
- bootstrap or placebo-based empirical power.

The methodology decision must be approved before implementation.

### PA-FR3. Effect injection

The engine shall support a defined treatment-effect injection policy.

Minimum first-release option:

- constant percentage uplift applied to the test aggregate during the simulated test window.

Potential later options:

- constant absolute effect;
- ramp-up;
- delayed start;
- decay or carryover;
- weekly varying effect.

The selected policy is recorded in the result.

### PA-FR4. Detection criterion

The method must define what constitutes a detected effect.

Possible criteria include:

- interval excludes zero;
- empirical placebo threshold is exceeded;
- estimated effect has the expected sign and meets a decision threshold;
- posterior probability exceeds an approved threshold.

The first-release criterion requires explicit methodology approval and must be visible in the UI and export.

### PA-FR5. Required outputs

For every scenario:

- requested and actual market share;
- test and control regions;
- duration;
- target uplift;
- absolute target effect;
- desired power;
- estimated power;
- target power met;
- minimum detectable effect;
- number of simulations;
- random seed;
- detection criterion;
- historical windows available and used;
- failure rate or invalid simulation count;
- warnings and limitations.

### PA-FR6. Minimum detectable effect

The application shall calculate the smallest effect meeting the desired power for the selected design, within an approved search tolerance.

#### Acceptance criteria

- Search bounds and tolerance are documented.
- Failure to identify an MDE within bounds is explicit.
- The result states whether MDE is relative or absolute.
- Low-volume KPIs and zero denominators are handled safely.

### PA-FR7. Required market share or duration

The application shall identify the smallest candidate test share or shortest candidate duration that meets the desired power, subject to design constraints.

### PA-FR8. Historical-data sufficiency

The engine shall report:

- historical observation count;
- date continuity;
- available simulation windows;
- region completeness;
- KPI variance;
- low-volume warnings;
- structural breaks or extreme outliers where assessed;
- predictor-to-history warning;
- blocking errors.

### PA-FR9. Reproducibility

Identical inputs, method version and seed produce identical results within approved numerical tolerance.

## 8. Platform selector

### 8.1 Initial platform profiles

Suggested profiles:

- Meta;
- Google Search;
- YouTube;
- Google Display;
- Programmatic Display;
- TikTok;
- Snapchat;
- Pinterest;
- LinkedIn;
- Connected TV;
- Linear TV;
- Online Video;
- Radio;
- Digital Audio;
- Out-of-Home;
- Direct Mail;
- Affiliate;
- Other Paid Media;
- Custom.

The first release may implement a smaller approved subset.

### 8.2 Selector behaviour

Selecting a platform shall:

- display relevant delivery fields;
- hide normally irrelevant fields;
- load platform-specific validation rules;
- retain a custom field option;
- record the profile and version used.

The statistical power result does not change solely because the platform label changes.

## 9. Common campaign inputs

Where applicable:

- total test budget;
- weekly budget;
- fixed or flexible budget;
- incremental or reallocated spend;
- campaign objective;
- optimisation event;
- target audience;
- eligible audience size;
- targeting restrictions;
- placements or inventory;
- bidding or buying method;
- creative format;
- start and end dates;
- geographic targeting method;
- control-region treatment;
- existing activity in control;
- expected spillover;
- forecast source and date;
- notes and assumptions.

## 10. Platform-profile inputs

## 10.1 Auction-based social, display and video

Examples: Meta, TikTok, YouTube, Google Display, programmatic display, LinkedIn, Snapchat and Pinterest.

Supported fields:

- CPM;
- impressions;
- reach;
- average frequency;
- eligible audience;
- clicks;
- CPC;
- click-through rate;
- video views;
- completed views;
- view-through rate;
- estimated conversions;
- estimated CPA;
- minimum recommended spend;
- minimum geographic size;
- delivery confidence range.

## 10.2 Paid search

Supported fields:

- budget;
- search volume;
- impressions;
- impression share;
- lost impression share due to budget;
- clicks;
- CPC;
- click-through rate;
- conversion rate;
- estimated conversions;
- estimated CPA;
- brand or non-brand scope;
- expected displacement or cannibalisation.

Frequency is not mandatory unless provided.

## 10.3 Television and online video

Supported fields:

- budget;
- CPM or cost per rating point;
- impressions;
- reach;
- frequency;
- GRPs or TVRs;
- spot or placement count;
- weekly weight;
- daypart or inventory constraints;
- completed views where relevant;
- spillover;
- minimum efficient spend.

## 10.4 Radio and digital audio

Supported fields:

- budget;
- reach;
- frequency;
- impressions or impacts;
- cost per thousand impacts;
- station or platform mix;
- geographic coverage;
- weekly weight;
- minimum efficient spend.

## 10.5 Out-of-home

Supported fields:

- budget;
- estimated impressions;
- reach;
- frequency;
- panel or location count;
- geographic coverage;
- exposure period;
- control spillover;
- minimum viable inventory.

## 10.6 Direct mail

Supported fields:

- mail volume;
- cost per item;
- total cost;
- deliverable households;
- delivery rate;
- response rate;
- conversion rate;
- regional penetration;
- contamination risk.

## 10.7 Custom profile

The analyst can define:

- field name;
- value;
- unit;
- required status;
- minimum and maximum thresholds;
- whether higher or lower is preferable;
- interpretation notes.

## 11. Spend-to-delivery calculations

### DF-FR1. Calculated delivery

Where inputs permit, GeoTestLab may calculate:

- impressions = budget divided by CPM times 1,000;
- clicks = budget divided by CPC;
- average frequency = impressions divided by reach;
- GRPs = reach percentage times frequency;
- mail volume = budget divided by unit cost.

These are examples. Formula availability depends on platform profile and approved definitions.

### DF-FR2. Supplied versus calculated values

Every delivery value shall be labelled as:

- supplied forecast;
- calculated;
- observed historical value;
- analyst assumption.

Where a supplied forecast conflicts materially with a simple calculated value, the tool shall flag the discrepancy rather than silently choose one.

### DF-FR3. Delivery thresholds

The user can define:

- minimum reach;
- minimum audience reach percentage;
- minimum and maximum frequency;
- minimum impressions;
- minimum clicks, views, GRPs or impacts;
- minimum weekly or total spend;
- minimum geographic size;
- maximum contamination.

Every threshold records its source:

- platform guidance;
- agency guidance;
- internal rule;
- analyst assumption;
- other.

### DF-FR4. Weekly profile

Supported patterns:

- even spend;
- custom weekly spend;
- front-loaded;
- back-loaded;
- ramp-up;
- learning period;
- blackout period;
- partial first or final week.

## 12. Effectiveness evidence

### 12.1 Evidence hierarchy

Suggested ranking:

1. prior experiment in the same market and platform;
2. prior experiment in a comparable market;
3. calibrated MMM estimate;
4. historical incremental CPA;
5. historical observed CPA;
6. platform or agency lift estimate;
7. analyst-defined low, central and high scenarios;
8. no effectiveness estimate.

The user can override the ranking with an explanation.

### 12.2 Supported bridges

Depending on evidence:

- incremental KPI = budget divided by incremental CPA;
- conversions = clicks times conversion rate;
- incremental KPI = impressions or reach times response rate;
- expected uplift from elasticity;
- expected effect sampled from a prior distribution.

All formulas and assumptions must be visible.

### 12.3 Uncertainty

Low, central and high values or a distribution shall be supported where practical.

Outputs may include:

- expected incremental KPI range;
- expected percentage uplift range;
- probability or simulation proportion exceeding MDE;
- spend required for target effect;
- sensitivity to effectiveness assumption.

### 12.4 No-effectiveness-data behaviour

Without an effect bridge, the application may conclude:

- whether the design can detect the target uplift;
- whether the budget can provide the forecast media delivery;
- whether delivery thresholds are met.

It shall not conclude:

- that the budget will produce the target uplift;
- expected incremental conversions;
- expected incremental CPA;
- expected return on investment.

Spend sufficiency for a detectable KPI effect shall be **unknown**.

## 13. Scenario matrix

Each scenario combines:

- regional design;
- actual market share;
- duration;
- target uplift;
- desired power;
- platform;
- spend;
- delivery forecast;
- effectiveness assumption.

Required columns:

- scenario name;
- test regions;
- control regions;
- match status;
- Counterfactual Confidence;
- duration;
- target uplift;
- MDE;
- estimated power;
- total and weekly spend;
- platform-relevant delivery metrics;
- expected KPI effect where calculable;
- delivery status;
- effect-plausibility status;
- recommendation eligibility;
- warnings.

## 14. Status dimensions

### Match quality

- acceptable;
- weak;
- insufficient data;
- failed.

### Counterfactual validation

- high confidence;
- moderate confidence;
- low confidence;
- insufficient data;
- exploratory only.

### Statistical power

- meets target;
- below target;
- insufficient data;
- failed.

### Media delivery

- meets thresholds;
- fails thresholds;
- incomplete;
- not assessed.

### Effect plausibility

- expected effect exceeds MDE;
- expected effect below MDE;
- uncertain;
- not assessable.

## 15. Recommendation logic

A scenario is fully eligible when it:

1. meets minimum match criteria;
2. has an acceptable counterfactual validation status;
3. meets the desired power;
4. satisfies region and duration constraints;
5. meets required media-delivery thresholds;
6. is expected to produce an effect at or above MDE, where effectiveness evidence exists.

The user chooses the optimisation objective:

- minimum test-market share;
- minimum spend;
- shortest duration;
- maximum power;
- custom ranking.

Where effect evidence is absent, the recommendation is conditional and explicitly states that spend sufficiency for KPI impact has not been established.

If no scenario qualifies, the product identifies one or more limiting factors:

- weak match;
- weak historical prediction;
- insufficient history;
- target effect too small;
- duration too short;
- test area too small;
- budget too low;
- reach too low;
- frequency outside threshold;
- control contamination;
- missing delivery forecast;
- missing effectiveness evidence.

## 16. Interface requirements

### 16.1 Primary questions

The first result area answers:

1. Are the regions credible?
2. What is the MDE?
3. Does the design meet target power?
4. Can the budget deliver adequately?
5. Is the expected effect detectable?
6. What is recommended?
7. What remains unknown?

### 16.2 Charts

Suggested charts:

- power by test-market share;
- MDE by duration;
- power by duration;
- power by spend scenario where an effect bridge exists;
- expected uplift versus MDE;
- reach and frequency by market share;
- required spend by target uplift;
- match quality versus power;
- feasibility frontier.

### 16.3 Missing-information guidance

The tool names the exact missing input, for example:

- historical KPI history is too short;
- planned duration is missing;
- four-week budget is missing;
- control treatment is undefined;
- reach forecast is missing for the 30 percent scenario;
- no frequency threshold is supplied;
- no effectiveness estimate is available.

### 16.4 Staleness

Any material change marks results stale, including:

- KPI data;
- regions;
- market weights;
- target uplift;
- power target;
- duration;
- platform;
- budget;
- delivery forecast;
- control treatment;
- effectiveness assumption;
- simulation configuration.

## 17. Data model

```python
@dataclass(frozen=True)
class TestSizingConfig:
    market: str
    geography_level: str
    metric: str
    frequency: str
    duration_periods: int
    target_uplifts: tuple[float, ...]
    target_power: float
    decision_threshold: float
    effect_direction: str
    market_size_measure: str
    candidate_market_shares: tuple[float, ...]
    random_seed: int
```

```python
@dataclass(frozen=True)
class PlatformConfig:
    platform: str
    campaign_objective: str | None
    optimisation_event: str | None
    target_audience: str | None
    eligible_audience_size: int | None
    geographic_targeting_method: str | None
    control_treatment: str
    custom_fields: Mapping[str, float | str | None]
```

```python
@dataclass(frozen=True)
class SpendScenario:
    name: str
    total_budget: float
    weekly_budget: tuple[float, ...]
    incremental_spend: bool
    replaces_existing_spend: bool
    forecast_source: str | None
    forecast_date: date | None
```

```python
@dataclass(frozen=True)
class DeliveryForecast:
    platform: str
    impressions: float | None
    reach: float | None
    frequency: float | None
    cpm: float | None
    clicks: float | None
    cpc: float | None
    grps: float | None
    conversions: float | None
    additional_metrics: Mapping[str, float]
```

```python
@dataclass(frozen=True)
class EffectivenessEvidence:
    source_type: str
    source_description: str | None
    metric: str
    low: float | None
    central: float | None
    high: float | None
    evidence_quality: str
```

```python
@dataclass(frozen=True)
class TestSizingScenarioResult:
    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    requested_market_share: float
    actual_market_share: float
    duration_periods: int
    target_uplift: float
    estimated_power: float | None
    minimum_detectable_effect: float | None
    total_budget: float | None
    delivery_metrics: Mapping[str, float | None]
    expected_incremental_kpi: float | None
    expected_uplift: float | None
    match_status: str
    counterfactual_status: str
    power_status: str
    delivery_status: str
    effect_status: str
    recommendation_eligible: bool
    warnings: tuple[str, ...]
```

## 18. Export requirements

The sizing export includes:

- tool and methodology version;
- input fingerprint;
- historical-data summary;
- selected regional design;
- matching and validation results;
- target uplift and power;
- duration;
- simulation method and seed;
- MDE and estimated power;
- platform and campaign setup;
- spend scenarios;
- delivery forecasts;
- thresholds;
- effectiveness evidence;
- expected effect scenarios;
- separate statuses;
- recommendation;
- override reason;
- warnings and limitations.

## 19. Automated testing

Tests shall cover:

- market-share construction;
- one-decimal-place display and unrounded calculation;
- force include and exclusion constraints;
- indivisible regions;
- fixed and variable duration;
- multiple uplift targets;
- power above and below target;
- MDE search;
- identical-seed reproducibility;
- insufficient history;
- discontinuous dates;
- low KPI volume;
- invalid simulations;
- platform-specific field rendering;
- Meta profile;
- paid-search profile;
- TV/video profile;
- custom fields;
- spend-to-impression calculation;
- frequency calculation;
- supplied versus calculated forecasts;
- no effectiveness evidence;
- low, central and high assumptions;
- expected effect above and below MDE;
- power pass with delivery fail;
- delivery pass with power fail;
- full pass with effect unknown;
- no qualifying scenario;
- recommendation objective;
- override rationale;
- staleness;
- complete export metadata.

## 20. Methodology decisions required before build

1. Primary simulation method.
2. Detection criterion.
3. Relative versus absolute effect injection.
4. Treatment-effect shape.
5. Handling of autocorrelation.
6. Use of rolling-origin or placebo windows.
7. Finite-sample policy.
8. Required number of simulations.
9. MDE search tolerance.
10. Confidence interval around estimated power.
11. Minimum historical window requirement.
12. Policy for exploratory fallback fits.
13. Default candidate shares and durations.
14. First-release platform profiles.
15. Evidence quality rules for spend-sufficiency conclusions.

## 21. Feature definition of done

The feature is complete when:

- power is calculated for the selected regional design;
- MDE is available;
- candidate shares and durations can be compared;
- platform can be selected;
- Meta is one profile among multiple channel types;
- budget and delivery can be entered or uploaded;
- calculated and supplied forecasts are distinguishable;
- effectiveness evidence can be added as observed evidence or scenarios;
- match, counterfactual, power, delivery and effect statuses remain separate;
- the tool does not claim spend sufficiency without an effect bridge;
- the limiting factor is identified when no design is feasible;
- the approved design can be frozen and exported;
- results are reproducible and regression-tested.

