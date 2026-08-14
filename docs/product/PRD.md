# GeoTestLab Product Requirements Document

**Document type:** Canonical product requirements document  
**Version:** 1.1
**Status:** Draft for product-owner review
**Date:** 14 August 2026
**Product owner:** Repository owner
**Implementation repository:** `papayasamosa/geotestlab_dev`  
**Repository baseline reviewed:** `main` at commit `6380c46d124535baa6702341d0ce02f6d2fe5478`
**Primary application:** Streamlit application launched from `geotestmatch.py`  

**Change summary:** Reconciled the reviewed baseline after PR2 power-methodology
evidence remediation and linked the proposed methodology ADR pack and manual
approval gate. No production power capability is approved by this update.

## 1. Document purpose

This document defines the product GeoTestLab is intended to be, the user problems it solves, the capabilities that form the product, and the requirements that should guide future development.

The product was built before a formal product PRD existed. This PRD therefore works backwards from three sources:

1. the behaviour currently implemented in the repository;
2. the product and methodology documentation already written for the tool; and
3. the product owner's newly defined requirement for prospective power analysis, test sizing and spend feasibility.

This is the canonical product PRD. It is distinct from the existing **GeoTestLab Maintainability and UX Hardening Programme**, which should be treated as a supporting engineering-delivery document rather than the definition of the product itself.

## 2. Requirement-status convention

Requirements in this document use the following labels:

- **Current:** implemented in the reviewed repository baseline and expected to remain part of the product.
- **Partially implemented:** present, but not yet complete against the target product requirement.
- **Planned:** approved product direction that is not yet implemented.
- **Proposed:** a product decision that still requires explicit approval.

Current behaviour is documented as the baseline, not automatically as the ideal final implementation. Future changes may improve the method or interface, but any deliberate behaviour change must be documented, tested and approved.

## 3. Executive summary

GeoTestLab is an analyst-led application for designing, validating, sizing and evaluating geographic marketing experiments.

It helps answer five connected questions:

1. **Which regions should be placed in test and control?**
2. **Do the proposed controls provide a credible historical counterfactual?**
3. **Is the proposed test large enough and long enough to detect the target effect?**
4. **Can the planned media budget deliver enough exposure to make that effect plausible?**
5. **After the test, what impact occurred and how uncertain is the estimate?**

The existing product already supports region matching, historical design validation, completed-test impact measurement and Bayesian Time-Based Regression. The major missing product capability is a prospective **Power Analysis and Test Sizing** stage that connects regional design, minimum detectable effect, duration, budget, media delivery and expected KPI response.

The product must preserve a clear distinction between:

- geographic and structural balance;
- historical counterfactual quality;
- statistical detectability;
- media delivery feasibility;
- expected effect plausibility; and
- observed post-test evidence.

No single metric should collapse these into an unexplained overall score.

## 4. Product vision

GeoTestLab will be a transparent, end-to-end workspace for non-US geographic marketing experimentation, enabling experienced measurement practitioners to move from an initial test brief to a defensible design, and from completed test data to a reproducible impact estimate.

The product should make sophisticated geo-testing methods usable without requiring the analyst to write code, while retaining enough methodological detail for the analyst to challenge, explain and defend every recommendation.

## 5. Product mission

Enable marketing measurement analysts to design and evaluate credible geo experiments by combining:

- regional balance;
- historical KPI behaviour;
- prospective power;
- media-delivery constraints;
- transparent counterfactual modelling;
- uncertainty quantification; and
- reproducible reporting.

## 6. Business problem

Marketing teams frequently want to understand whether a regional media pause, campaign launch, spend increase, creative change, channel change or other intervention caused an incremental change in outcomes.

A geographic experiment can provide useful evidence when some regions receive the treatment and other regions provide a credible counterfactual. The challenge is that the untreated outcome for the test regions is never observed. The validity of the result depends on whether the control regions credibly represent what would have happened without treatment.

Current analytical workflows often separate the problem into disconnected tasks:

- select regions using demographic intuition;
- assess historical tracking in a separate model;
- ask the media team whether the budget is enough;
- estimate test impact later in a different notebook or tool;
- manually reconcile results and caveats for stakeholders.

This creates several risks:

- structurally similar regions may not track the KPI historically;
- historically correlated controls may be contaminated or implausible;
- a design may be statistically underpowered;
- a budget may be spread too thinly across too large a test area;
- adequate reach may still be insufficient to cause a detectable KPI effect;
- users may confuse model fit with evidence of impact;
- changing settings after seeing results may lead to cherry-picking;
- analytical outputs may not be reproducible.

GeoTestLab exists to bring these decisions into one governed workflow.

## 7. Product scope

### 7.1 In scope

GeoTestLab shall support the following experiment lifecycle:

1. define the market, geography, KPI and experiment constraints;
2. construct test and control groups;
3. assess structural or historical KPI-pattern balance;
4. validate the proposed counterfactual using historical time-series data;
5. estimate power and minimum detectable effect;
6. assess test size, duration and media-spend feasibility;
7. freeze and export the approved design;
8. evaluate a completed test using regularised counterfactual models and placebo analysis;
9. estimate impact using Bayesian Time-Based Regression;
10. inspect diagnostics, uncertainty and methodological limitations;
11. export a reproducible analysis record.

### 7.2 Market scope

The product is designed for UK and international non-US markets. Available markets and geography levels are driven by the built-in geography workbook or by uploaded custom KPI geographies.

US DMA support is not part of the current product scope. It may be considered as a separate future extension with its own geography source, market definitions and methodological validation.

### 7.3 Intervention scope

The tool should support geographic experiments involving, for example:

- media launches;
- media pauses or holdouts;
- spend increases or decreases;
- channel reallocations;
- creative changes;
- targeting changes;
- regional campaign treatments;
- other market-level interventions with clearly defined test and control exposure.

### 7.4 Platform scope

The statistical design must be platform-independent.

The prospective sizing workflow shall include a platform or channel selector so that relevant delivery inputs can be collected for different media types. Meta is one supported platform profile, not the product's default architecture.

## 8. Non-goals

The following are outside the current product scope unless separately approved:

- proving causality automatically;
- replacing experimental judgement with a black-box recommendation;
- campaign activation or direct writes into advertising platforms;
- automated bid, audience or creative optimisation;
- user authentication and permission management;
- a multi-tenant production database;
- a hosted job queue;
- an external API without a confirmed consumer;
- replacing Streamlit solely for aesthetic reasons;
- replacing the current matching, Elastic Net, LASSO or Bayesian TBR approaches without a separately approved methodology change;
- guaranteeing that a forecast budget will cause a specific uplift;
- presenting platform forecasts as independent evidence of incrementality;
- supporting every geography system without an appropriate region mapping or uploaded dataset.

## 9. Users and personas

### 9.1 Marketing measurement analyst

Primary user.

Needs to:

- build a credible test and control split;
- understand trade-offs between representativeness, match quality, power and spend;
- configure and defend the method;
- compare alternative designs;
- identify when a test should not proceed;
- evaluate completed results;
- export evidence and assumptions.

### 9.2 Data scientist

Needs to:

- inspect model inputs and outputs;
- understand every transformation and assumption;
- validate numerical behaviour;
- access advanced controls and diagnostics;
- reproduce an analysis;
- extend the methodology safely.

### 9.3 Marketing manager or media planner

Needs to:

- provide budget and campaign constraints;
- provide platform or agency delivery forecasts;
- understand what market size is feasible;
- understand whether the plan is likely to create a detectable effect;
- receive a clear list of missing information.

### 9.4 Marketing stakeholder

Needs to:

- understand the approved test design;
- see the expected detectable effect and main risks;
- understand the completed-test conclusion and uncertainty;
- distinguish an indicative result from strong evidence;
- receive a concise, exportable summary.

### 9.5 Developer or maintainer

Needs to:

- understand the product contract;
- separate existing behaviour from planned functionality;
- modify code without silent numerical drift;
- use typed interfaces and automated tests;
- trace implementation work to requirements.

## 10. Jobs to be done

### JTBD-1: Build the regional design

When planning a geographic experiment, the analyst needs to create test and control groups that meet business constraints and are balanced on relevant regional characteristics.

### JTBD-2: Validate the counterfactual

Before launching the test, the analyst needs to determine whether the proposed controls historically predict the test group's KPI well enough to support a credible counterfactual.

### JTBD-3: Size the test

The analyst needs to know what region share, duration and effect size can be detected with the available historical data.

### JTBD-4: Check spend sufficiency

The analyst needs to know whether the planned budget can deliver sufficient exposure and, where effectiveness evidence exists, whether the expected KPI effect is at least as large as the minimum detectable effect.

### JTBD-5: Freeze an approved design

The analyst needs to preserve the approved regions, dates, assumptions, settings and power result before the test begins.

### JTBD-6: Measure impact

After the test, the analyst needs to estimate the actual and counterfactual outcomes, calculate uplift and determine whether the result is unusual relative to historical placebo periods.

### JTBD-7: Quantify uncertainty

The analyst needs a probabilistic impact estimate with uncertainty intervals and sampling diagnostics.

### JTBD-8: Explain whether the result is trustworthy

The analyst needs diagnostics that separate counterfactual credibility from the direction and magnitude of the estimated effect.

### JTBD-9: Reproduce and review

The analyst or another reviewer needs to recreate the analysis from exported configuration, data identity and methodology metadata.

## 11. Product goals

### G1. End-to-end experiment support

Support the complete workflow from regional design to completed-test analysis.

### G2. Design credibility

Make it difficult to proceed without understanding structural balance, historical tracking and contamination risks.

### G3. Prospective detectability

Allow users to calculate power and minimum detectable effect before launching a test.

### G4. Spend-aware design

Connect test size and duration to media budget, delivery and expected KPI response without overstating what the available evidence supports.

### G5. Transparent uncertainty

Present uncertainty and methodological limitations before confident language.

### G6. Reproducibility

Link every completed analysis to its data, settings, seed, methodology and tool version.

### G7. Guided usability

Help occasional users identify the next required action while retaining advanced controls for expert users.

### G8. Safe evolution

Protect current numerical behaviour and make future methodology changes explicit and reviewable.

## 12. Product principles

1. **Match quality, power, delivery and impact are separate dimensions.**
2. **Historical fit is necessary but not sufficient for causal interpretation.**
3. **A statistically detectable effect is not automatically commercially plausible.**
4. **Media exposure is not the same as incremental KPI impact.**
5. **No silent data loss, fallback or method substitution.**
6. **Current and stale results must be visibly different.**
7. **Defaults should guide, not conceal assumptions.**
8. **Advanced settings remain available and explainable.**
9. **Random processes are seeded and recorded where reproducibility is expected.**
10. **The product may recommend not running a test.**
11. **The approved pre-test design should be frozen before outcomes are examined.**
12. **Exports must preserve enough information for independent review.**

## 13. Target product workflow

The target workflow contains five product stages. The current four-tab interface may be retained during transition, but the product model should reflect these stages.

### Stage 1: Define and match regions

- choose Structural or KPI Pattern matching;
- select market or upload custom geography data;
- define test and control constraints;
- build candidate groups;
- inspect balance and market share.

### Stage 2: Validate the design

- upload historical KPI data;
- review data quality and mapping;
- choose frequency and historical period;
- compare control-selection methods;
- inspect rolling-origin, bias, overfitting, residual and placebo diagnostics;
- assess Counterfactual Confidence.

### Stage 3: Size and power the test

- select target uplift or calculate minimum detectable effect;
- define or compare duration;
- compare candidate test-market shares;
- select media platform or channel;
- enter budget and delivery assumptions;
- connect expected delivery to effect where evidence exists;
- determine whether a feasible design exists;
- freeze the approved design.

### Stage 4: Measure completed-test impact

- define pre, test and optional post periods;
- inherit the approved design where available;
- estimate actual and counterfactual totals;
- calculate uplift;
- compare observed uplift with placebo windows;
- review method comparison and diagnostics.

### Stage 5: Bayesian analysis and reporting

- select the validated control method;
- configure priors, lags and noise structure;
- run Bayesian TBR;
- inspect predictive intervals, uplift distribution and MCMC diagnostics;
- generate stakeholder and technical exports.

## 14. Current product baseline

The following capabilities are implemented in the reviewed repository and form the baseline product contract.

### 14.1 Application and architecture

- Streamlit application with four workflow tabs.
- Python 3.11 runtime.
- Built-in market workbook.
- `geotestmatch.py` remains the application entry point.
- Data ingestion, matching, validation and Bayesian domain logic are extracted
  into Streamlit-free packages behind the application adapter boundary.
- The matching and canonical data packages are Streamlit-free and typed.
- The application remains the Streamlit entry point and UI monolith.

### 14.2 Region matching

- Structural matching using population and demographic features.
- KPI Pattern matching using historical KPI series indexed to each region's own mean.
- Manual selection of test and control.
- Manual test selection with automated control matching.
- Rules-based automated test and control construction.
- Test and control inclusion and exclusion constraints.
- Global exclusion from both groups.
- Target test-market share with tolerance.
- Basic greedy nearest-neighbour strategy.
- Intermediate hill-climbing strategy.
- Advanced seeded stochastic search.
- Optional one-to-one match ratio.
- Search across control-group sizes.
- User-adjustable structural feature weights.
- Market-share display to one decimal place.
- Structural diagnostics and exports.

### 14.3 KPI data handling

- Simple and aggregated Excel layouts.
- Automatic date-column and metric-column detection.
- Region mapping using workbook references and direct matches.
- Structured data-quality report.
- Rejected and unmapped row downloads.
- Frequency inference.
- Missing-date reporting.
- Tracking-outage and missing-period exclusion.
- Blocking errors for unusable inputs and warnings for non-blocking concerns.

### 14.4 Design validation

- Weekly and daily data.
- Frequency mismatch acknowledgment gate.
- Structurally matched controls.
- Data-optimised controls using all eligible non-test regions.
- Data-optimised controls excluding force-excluded regions.
- User-selected controls.
- Elastic Net and LASSO regularisation.
- Time-series cross-validation where sufficient history exists.
- Explicit exploratory fallback where safe cross-validation is unavailable.
- Optional frequency-aware lagged controls.
- Pre-period correlation, R-squared, sMAPE and RMSE.
- Durbin-Watson residual diagnostic.
- Rolling-origin validation.
- Holdout bias.
- Overfitting gap.
- Placebo windows.
- Counterfactual Confidence with explanatory drivers.

### 14.5 Completed-test evaluation

- Pre, test and optional post windows.
- Actual and counterfactual totals.
- Absolute and percentage uplift.
- Observed uplift compared with placebo distribution.
- Placebo percentile, empirical tail measures and z-score.
- Method comparison.
- Charts and data exports.

### 14.6 Bayesian Time-Based Regression

- Evaluate-mode prerequisite.
- User selection of validated control method.
- No silent fallback when a data-optimised method selects no controls.
- Optional lagged predictors inherited from validation.
- Weak or structurally informed coefficient priors.
- Correlation-informed prior scale.
- Optional AR(1) noise handling subject to continuity requirements.
- PyMC sampling.
- Fitted-mean pre-period interval.
- Posterior predictive test and post intervals.
- Posterior predictive uplift distribution.
- Posterior probability that uplift is positive.
- R-hat, ESS, MCSE and divergence diagnostics.
- Chart-data exports.

### 14.7 Engineering baseline

- Reproducible Python dependency definitions and lock files.
- GitHub Actions for tests, lock verification and numerical golden regressions.
- Package coverage gate.
- Deterministic numerical characterisation fixtures.
- Typed data-quality and matching objects.
- Explicit random seed for guided matching.

## 15. Functional requirements

## FR-1. Market and geography configuration

**Status:** Current, with planned extensibility.

GeoTestLab shall allow the analyst to select a market and geography level from the built-in geography source or use uploaded custom geographies through KPI Pattern mode.

### Acceptance criteria

- Market options reflect the available source data rather than a hardcoded country list.
- Geography levels reflect the hierarchy available for the selected market.
- The application shows the regional market-size measure used by the design.
- Unsupported or unmapped geographies are reported before modelling.
- Custom geographies can be used without requiring a built-in demographic record.
- US DMA support is not implied by generic market-agnostic wording.

## FR-2. KPI ingestion and data-quality contract

**Status:** Current, with continued hardening.

GeoTestLab shall accept historical KPI data, reshape it into a consistent analytical structure and produce a structured quality report before modelling.

### Acceptance criteria

The report includes:

- parsed file layout;
- selected aggregation and metric fields;
- canonical regional KPI source fingerprint and selected market-size semantics;
- source rows and retained observations;
- date range and inferred frequency;
- expected and missing dates;
- raw, mapped and unmapped regions;
- duplicate keys;
- missing, invalid and non-numeric observations;
- rejected rows;
- blocking errors;
- non-blocking warnings.

The user can download rejected and unmapped rows where available.

## FR-3. Matching method selection

**Status:** Current.

The analyst shall select either:

- **Structural matching**, using population-weighted demographic or market features; or
- **KPI Pattern matching**, using the historical shape of regional KPI series.

### Acceptance criteria

- The selected method changes the relevant input controls and terminology.
- KPI Pattern values are normalised consistently for shape comparison.
- KPI Pattern mode does not misleadingly label KPI volume as population.
- Structural feature weights are available only when structurally meaningful.
- The selected method is recorded in the experiment configuration and export.

## FR-4. Test and control construction

**Status:** Current.

GeoTestLab shall support:

- manual test and control selection;
- manual test selection with automated controls;
- rules-based automated construction of both groups.

### Acceptance criteria

- Test and control groups cannot overlap.
- The user can exclude a region from both groups.
- The user can force or prevent test eligibility.
- The user can force or prevent control eligibility.
- Contradictory constraints produce a visible structured blocker.
- Persisted selections are not silently removed to hide a conflict.
- Automated search is deterministic for identical inputs and seed.
- Requested and actual market share are reported separately.

## FR-5. Matching strategies and diagnostics

**Status:** Current.

GeoTestLab shall provide bounded matching strategies with explainable trade-offs.

### Acceptance criteria

- Basic, intermediate and advanced strategies are accurately named and explained.
- A one-to-one control ratio can be enforced.
- A control-group size range can be searched where applicable.
- The advanced strategy records its seed and search intensity.
- Results include test and control regions, market shares, group sizes and balance metrics.
- Diagnostics include feature-level balance and search behaviour.
- Changing a material matching input marks existing results stale.

## FR-6. Historical counterfactual validation

**Status:** Current, with planned modular extraction.

GeoTestLab shall evaluate whether proposed controls predict the test group's historical KPI.

### Acceptance criteria

- Validation operates on weekly and daily data.
- A likely frequency mismatch is surfaced and must be acknowledged.
- All methods use the same selected pre-period for comparison.
- The application compares structural, data-optimised and user-selected control methods where applicable.
- Regularisation and hyperparameter selection are time-series safe.
- Exploratory fallback fits are visibly labelled and excluded from formal confidence conclusions.
- Users can inspect controls selected by each method.
- Row loss from missing data or lags is reported.

## FR-7. Rolling-origin, bias, overfitting and residual diagnostics

**Status:** Current.

GeoTestLab shall distinguish in-sample fit from out-of-sample predictive credibility.

### Acceptance criteria

Results include:

- pre-period correlation;
- pre-period R-squared;
- pre-period sMAPE and RMSE;
- rolling-origin sMAPE and RMSE;
- average rolling-origin bias;
- overfitting gap;
- Durbin-Watson statistic;
- traffic-light interpretations with documented thresholds;
- available and used validation-fold counts;
- warnings when historical windows are insufficient or discontinuous.

## FR-8. Placebo analysis

**Status:** Current, with methodology clarification planned.

GeoTestLab shall estimate the distribution of apparent effects that arise in untreated historical windows.

### Acceptance criteria

- Placebo windows use the selected frequency and an appropriate duration.
- Discontinuous windows are not silently treated as contiguous.
- The number of available and used windows is reported.
- Any cap samples windows across the historical period rather than only the earliest windows.
- Outputs clearly describe empirical tail measures rather than overstate formal p-values.
- The attainable resolution is reported.
- Exploratory fallback windows are identified and treated according to an approved policy.

## FR-9. Counterfactual Confidence

**Status:** Current.

GeoTestLab shall provide a summary assessment of counterfactual credibility that is separate from the observed effect conclusion.

### Acceptance criteria

- The rating is driven by documented validation components.
- The primary and secondary diagnostic hierarchy is explicit.
- The application lists all material drivers of a moderate, low or insufficient rating.
- A high estimated uplift cannot override a weak counterfactual rating.
- An exploratory fallback fit cannot receive a formal confidence rating.

## FR-10. Prospective power analysis

**Status:** Planned.

GeoTestLab shall estimate whether a proposed geo-test can detect a target effect before the test begins.

### Acceptance criteria

For every candidate design, the application reports:

- selected test and control regions;
- requested and actual test-market share;
- historical period used;
- planned duration;
- target uplift;
- absolute target effect;
- desired power;
- estimated power;
- whether target power is met;
- minimum detectable effect;
- method used;
- simulation settings and seed where applicable;
- warnings and limitations.

The power analysis must use the proposed regional design and historical KPI behaviour rather than a generic market-level calculator that ignores the selected controls.

Detailed requirements are defined in `power-analysis-and-test-sizing.md`.

## FR-11. Test-size and duration scenarios

**Status:** Planned.

The analyst shall be able to compare alternative market shares and durations.

### Acceptance criteria

- Default candidate test shares are configurable.
- Candidate groups are based on a selected market-size measure, not region count.
- The analyst can lock duration when the business brief fixes it.
- The analyst can compare multiple target uplifts.
- The application identifies the smallest design that meets the power target, subject to matching and region constraints.
- Indivisible-region limitations are visible.

## FR-12. Platform and channel selection

**Status:** Partially implemented — generic profile schema and Meta profile registration exist; selector and dynamic workflow remain planned.

The test-sizing workflow shall include a platform or channel selector.

### Acceptance criteria

- Statistical power does not depend on platform selection.
- Platform selection changes the media-delivery fields and validation rules shown.
- Meta is available as one platform profile.
- Search, video/TV, display/social, audio/radio, out-of-home, direct mail and custom profiles can be supported.
- The user can add custom delivery fields.
- Platform and campaign configuration are recorded in the design export.

## FR-13. Media-delivery feasibility

**Status:** Planned.

GeoTestLab shall assess whether the available budget can deliver the required media exposure within the proposed test area.

### Acceptance criteria

Where applicable, the analyst can enter or upload:

- total and weekly budget;
- CPM or CPC;
- impressions;
- reach;
- frequency;
- audience size;
- clicks, views, GRPs, impacts, mail volume or another platform-relevant measure;
- minimum delivery thresholds;
- source and date of the forecast;
- campaign objective and optimisation event;
- control-region treatment;
- incremental or reallocated-spend status;
- spillover or contamination assumptions.

The application distinguishes externally supplied forecasts from values calculated from budget and unit costs.

## FR-14. Effect plausibility and spend sufficiency

**Status:** Planned.

GeoTestLab shall only conclude that planned spend is likely to produce a detectable KPI effect when an explicit bridge exists between media delivery and KPI response.

Permitted evidence sources include:

- prior experiment in the same market and platform;
- comparable-market experiment;
- calibrated MMM estimate;
- historical incremental CPA;
- historical observed CPA;
- response or conversion rate;
- elasticity;
- platform or agency lift forecast;
- user-defined low, central and high scenarios.

### Acceptance criteria

- The evidence source and quality are recorded.
- User assumptions are labelled as scenarios rather than observations.
- Where possible, outputs include expected incremental KPI, expected uplift and an uncertainty range.
- Expected uplift is compared with minimum detectable effect.
- Where no effect bridge exists, the product reports statistical detectability and media delivery separately and marks spend sufficiency as unknown.
- The product never implies that reach or frequency alone proves a target uplift is plausible.

## FR-15. Integrated design recommendation

**Status:** Planned.

GeoTestLab shall compare complete design scenarios and recommend a feasible option.

### Acceptance criteria

The recommendation considers separately:

- match quality;
- counterfactual validation;
- power;
- media delivery;
- effect plausibility;
- region constraints;
- duration;
- cost.

The product recommends the smallest or least costly qualifying design according to an explicit user-selected objective.

If no design qualifies, the product identifies the limiting factor rather than returning a generic failure.

The analyst may override a recommendation, but the override reason is required and exported.

## FR-16. Approved design freeze

**Status:** Planned.

The analyst shall be able to freeze the approved pre-test design before the test begins.

### Acceptance criteria

The frozen design includes:

- test and control regions;
- excluded regions;
- KPI;
- historical period;
- planned test dates and duration;
- matching and validation method;
- power result and minimum detectable effect;
- platform and campaign setup;
- budget and delivery assumptions;
- effect-plausibility assumptions;
- methodology and tool version;
- data fingerprints;
- approval timestamp;
- analyst notes.

Later changes create a new design version rather than silently replacing the approved record.

## FR-17. Completed-test impact measurement

**Status:** Current.

GeoTestLab shall estimate the completed test's impact using the approved or selected design.

### Acceptance criteria

- Pre, test and optional post windows are explicit.
- The analysed period count is compared with the planned period count.
- Excluded outage periods are reported.
- Actual and counterfactual totals are shown.
- Absolute and percentage uplift are shown.
- Pre-period credibility is shown before impact interpretation.
- Observed uplift is compared with placebo results.
- Test-window changes after design freeze are clearly identified.

## FR-18. Bayesian Time-Based Regression

**Status:** Current, with planned modular extraction and profiling.

GeoTestLab shall provide a Bayesian counterfactual estimate using the selected validated controls.

### Acceptance criteria

- Bayesian analysis requires an eligible completed-test validation result.
- The exact controls and model terms are shown before sampling.
- Empty control selections do not trigger a silent fallback.
- Prior choice and rationale are visible.
- Frequency, lag and continuity settings are inherited consistently.
- The pre-period displays fitted-mean uncertainty.
- Test and post periods display posterior predictive uncertainty.
- The headline uplift interval includes observation noise.
- Posterior probability language is not described as a frequentist p-value.
- Sampling diagnostics include R-hat, ESS, MCSE and divergences.
- A model with failed diagnostics is not presented as trustworthy.

## FR-19. Result hierarchy and interpretation

**Status:** Partially implemented.

The first result area shall distinguish:

1. design credibility;
2. statistical detectability;
3. media-delivery feasibility;
4. effect plausibility;
5. observed effect direction and magnitude;
6. uncertainty;
7. principal warning;
8. recommended next action.

Detailed method comparison, coefficients, placebo distributions and MCMC diagnostics remain available below or within advanced sections.

## FR-20. Workflow status and staleness

**Status:** Partially implemented.

GeoTestLab shall maintain explicit workflow state across the experiment lifecycle.

### Acceptance criteria

Each stage can be:

- not started;
- configured;
- complete;
- needs attention;
- stale;
- frozen.

Every result is linked to a deterministic input fingerprint. A material input change marks dependent results stale and does not silently reuse them.

## FR-21. Guided and advanced experience

**Status:** Partially implemented.

The default interface shall prioritise essential decisions while retaining expert controls.

### Acceptance criteria

- The next required action is visible.
- Default values are labelled and explained.
- Advanced changes do not automatically run a model.
- Display-only changes do not invalidate analytical results.
- Technical controls remain accessible.
- Long sections use progressive disclosure rather than hiding required information.

## FR-22. Export and reproducibility

**Status:** Current in parts, planned as a complete experiment record.

Exports shall contain sufficient information to reproduce and review the analysis.

### Acceptance criteria

Where applicable, exports include:

- tool version;
- methodology version;
- generated timestamp;
- input fingerprint;
- package versions;
- data-quality summary;
- market and geography;
- KPI and frequency;
- test and control regions;
- exclusions;
- matching settings and seed;
- validation settings;
- dates and duration;
- power and minimum detectable effect;
- platform and budget assumptions;
- delivery forecasts;
- effectiveness assumptions;
- observed impact;
- uncertainty intervals;
- diagnostics;
- warnings;
- recommendation or override rationale.

## FR-23. Error handling

**Status:** Partially implemented.

GeoTestLab shall provide actionable user-facing errors and preserve technical detail for diagnosis.

### Acceptance criteria

- Domain errors identify the affected field, region or date where practical.
- Raw stack traces are not the default user experience.
- Technical details are available in an expander or log.
- Core analytical functions do not terminate the Streamlit process directly.
- Partial results are labelled and do not appear complete.

## FR-24. Accessibility

**Status:** Partially implemented.

### Acceptance criteria

- All primary controls are keyboard usable.
- Focus is visible.
- Status does not rely on colour alone.
- Text and controls meet reasonable WCAG AA contrast targets.
- The workflow remains usable at 200 percent zoom.
- Narrow screens do not hide the primary action or active status.

## 16. Data requirements

### 16.1 Built-in structural data

The product requires a versioned market workbook containing:

- market sheets;
- regional identifiers;
- geography hierarchy;
- population;
- optional mapping references;
- numeric structural features.

### 16.2 Historical KPI data

The product should support:

- weekly or daily observations;
- region;
- metric;
- date;
- numeric KPI value;
- one to two years of history where possible;
- consistent regional coverage.

### 16.3 Market-size data

Prospective sizing requires a regional measure such as:

- population;
- customers;
- historical KPI volume;
- revenue;
- addressable audience;
- another approved weight.

### 16.4 Media-plan data

Depending on platform, this may include:

- budget;
- CPM or CPC;
- reach;
- frequency;
- impressions;
- clicks;
- views;
- GRPs or impacts;
- audience size;
- response or conversion assumptions;
- platform delivery constraints.

### 16.5 Data provenance

Every imported or calculated input should record:

- source;
- file or forecast date;
- analyst notes;
- transformation status;
- whether the value is observed, forecast, calculated or assumed.

## 17. Methodology requirements

### 17.1 Transparency

Every analytical output must identify the method and assumptions that produced it.

### 17.2 Numerical stability

- Detect non-finite values.
- Avoid silent clipping.
- Record random seeds.
- Use approved numerical tolerances.
- Preserve the distinction between fitted-mean and predictive uncertainty.

### 17.3 Time-series integrity

- Do not use regular random K-fold cross-validation for ordered time-series data.
- Do not treat missing dates as adjacent periods.
- Make lag duration frequency-aware.
- Report historical window counts and continuity.

### 17.4 Placebo interpretation

Placebo tail measures must be described as empirical evidence relative to the available placebo distribution, with finite resolution and overlapping-window limitations stated.

### 17.5 Power methodology

The initial power method should be simulation-based and aligned with the planned evaluation method where feasible. The final method, detection criterion and treatment-effect injection policy require explicit methodology approval before implementation.

### 17.6 Causal language

The product must not claim that an uplift estimate is causal unless the design assumptions, treatment separation, contamination controls and counterfactual credibility support that interpretation.

## 18. Suggested core data model

```python
@dataclass(frozen=True)
class ExperimentIdentity:
    experiment_id: str
    version: int
    tool_version: str
    methodology_version: str
    input_fingerprint: str
    created_at: datetime
    frozen_at: datetime | None
```

```python
@dataclass(frozen=True)
class ExperimentDefinition:
    market: str
    geography_level: str
    metric: str
    frequency: str
    matching_method: str
    test_regions: tuple[str, ...]
    control_regions: tuple[str, ...]
    excluded_regions: tuple[str, ...]
    historical_period: tuple[date, date]
    planned_test_period: tuple[date, date] | None
```

```python
@dataclass(frozen=True)
class DesignAssessment:
    match_status: str
    counterfactual_status: str
    power_status: str
    delivery_status: str
    effect_plausibility_status: str
    principal_warnings: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class AnalysisIdentity:
    tool_version: str
    methodology_version: str
    input_fingerprint: str
    created_at: datetime
```

Existing typed matching and data-quality objects should be retained and incorporated rather than duplicated.

## 19. Non-functional requirements

### NFR-1. Reproducibility

- Python and dependency versions are recoverable.
- Randomised processes are seeded.
- Inputs and outputs have fingerprints.
- Approved designs are versioned.

### NFR-2. Maintainability

- Domain modules do not depend on Streamlit.
- Public analytical functions have type hints and docstrings.
- UI, state, analytical logic and reporting are separated.
- Large untyped result dictionaries are migrated to typed results.

### NFR-3. Regression safety

- Existing deterministic workflows have golden outputs.
- Intentional numerical changes require documented approvals.
- CI blocks merge on failed numerical regression tests.
- Power-analysis scenarios receive their own deterministic fixtures.

### NFR-4. Performance

- Ordinary display interactions do not rerun expensive models.
- KPI parsing is cached by content and configuration.
- Matching and power simulations use bounded profiles.
- Slow Bayesian and power simulations can be separated from the fast test suite.
- No optimisation is accepted without numerical parity or approved change evidence.

### NFR-5. Reliability

- No silent method fallback.
- No silent data loss.
- Stale results never appear current.
- Partial and exploratory results are labelled.
- Important warnings are not globally suppressed.

### NFR-6. Security and confidentiality

- Uploaded data remains local to the application process unless deployment architecture states otherwise.
- No external telemetry or data transmission is introduced without approval.
- Sample fixtures are synthetic or authorised.
- Error messages avoid exposing sensitive row-level values unnecessarily.

### NFR-7. Accessibility

- Keyboard usability and visible focus.
- Text labels for status.
- Reasonable WCAG AA contrast.
- Usability at 200 percent zoom.

### NFR-8. Documentation

The repository shall maintain:

- canonical product PRD;
- user guide;
- methodology guide;
- architecture guide;
- data-format guide;
- release notes;
- analytical decision records;
- implementation roadmap.

## 20. Success metrics

### 20.1 Product and usability

- Time from app open to a valid first regional design.
- Percentage of users who complete data validation before attempting modelling.
- Percentage of proposed tests with a recorded power analysis before launch.
- Percentage of approved tests with a frozen design record.
- Reduction in stale-result incidents.
- User ability to distinguish counterfactual confidence from evidence of effect.
- User ability to identify the limiting factor in an infeasible design.

### 20.2 Analytical quality

- Percentage of completed analyses with sufficient rolling-origin validation.
- Percentage of reported tests with documented placebo resolution.
- Percentage of Bayesian results with all required diagnostics passing.
- Zero unapproved changes to numerical golden outputs.
- Percentage of power recommendations reproduced from saved configuration.

### 20.3 Engineering

- At least 90 percent coverage of extracted analytical packages, with stronger branch coverage on critical decision logic.
- CI on every pull request.
- No Streamlit imports in domain and modelling modules.
- Current architecture documentation.
- Reproducible clean installation.

### 20.4 Operational

- New maintainer can run the application and tests from the README.
- A failed downstream model does not destroy upstream completed work.
- Release dependencies and methodology version are recoverable.

## 21. Current-to-target gap summary

### Implemented and retained

- structural and KPI Pattern matching;
- manual and automated group construction;
- deterministic constraints;
- data-quality reporting;
- regularised historical validation;
- rolling-origin and placebo diagnostics;
- impact measurement;
- Bayesian TBR;
- numerical regression protection;
- CI and dependency locking.

### Partially implemented

- modular analytical architecture;
- typed result objects beyond data and matching;
- workflow-level status and fingerprints;
- guided result hierarchy;
- full experiment exports;
- accessibility and responsive workflow;
- current methodology and architecture documentation.

### Not yet implemented

- prospective power analysis;
- minimum detectable effect calculator tied to selected regions;
- test-size and duration scenario comparison;
- platform-aware media-delivery inputs;
- spend-to-exposure calculation;
- effect-plausibility bridge;
- integrated design recommendation;
- approved design freeze and versioning.

## 22. Delivery roadmap

### Phase 0. Adopt the product contract

- approve this PRD;
- place it in the repository as the canonical product reference;
- reconcile README and project documentation;
- relabel the existing hardening PRD as an engineering companion;
- create decision records for unresolved methodology choices.

### Phase 1. Complete behaviour-preserving modularisation

- extract validation core;
- extract placebo and rolling-origin modules;
- extract Bayesian core;
- introduce typed validation and Bayesian results;
- complete state fingerprints and workflow status;
- preserve numerical goldens.

### Phase 2. Power-analysis methodology spike

- choose the initial detection criterion;
- choose simulation and effect-injection policy;
- validate against hand-calculable and synthetic cases;
- test sensitivity to short history, low volume and autocorrelation;
- define outputs and limitations.

### Phase 3. Power-analysis MVP

- selected-design power;
- minimum detectable effect;
- candidate market-share scenarios;
- fixed or variable duration;
- reproducible simulation seed;
- export and staleness handling.

### Phase 4. Platform-aware delivery feasibility

- platform selector;
- Meta and other initial platform profiles;
- budget, CPM/CPC, reach, frequency and audience inputs;
- calculated versus supplied forecast distinction;
- delivery thresholds;
- scenario comparison.

### Phase 5. Effect plausibility and recommendation

- effectiveness-evidence hierarchy;
- low, central and high assumptions;
- expected KPI effect;
- comparison with minimum detectable effect;
- spend requirement scenarios;
- integrated recommendation and limiting-factor explanation.

### Phase 6. Approved design records and reporting

- freeze/version design;
- stakeholder summary;
- technical methodology export;
- compare planned versus analysed design after completion;
- production naming and release documentation.

## 23. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Formalising current behaviour preserves an undesirable limitation | Mark current behaviour separately from approved target behaviour and require explicit methodology decisions. |
| Power calculator creates false certainty | Use simulation, show assumptions, separate detectability from delivery and effect plausibility. |
| Budget is mistaken for expected incrementality | Require an explicit effectiveness bridge and report unknown where absent. |
| Many scenarios encourage cherry-picking | Freeze approved design and record overrides and scenario-selection rationale. |
| Refactor changes numerical results | Preserve golden baselines and review intentional changes separately. |
| Platform fields become unmanageable | Use platform profiles plus a custom-field model rather than hardcoding all channels into one form. |
| Small regional KPI volumes make power unstable | Surface data sufficiency, simulation uncertainty and low-volume warnings. |
| Control contamination is not detectable from data alone | Require explicit treatment and spillover inputs, with manual exclusions and warnings. |
| Documentation becomes stale | Include documentation updates in definition of done and release checklist. |
| Bayesian or power simulations are too slow | Use bounded profiles, caching and separate slow CI workflows. |

## 24. Open product and methodology decisions

1. What is the primary power-analysis detection criterion for the first release?
2. Should the first power engine use historical residual simulation, placebo injection, model-based simulation or more than one method?
3. How should positive, negative and two-sided target effects be handled?
4. How should ramp-up, delayed effect and carryover be represented in power simulations?
5. Which market-size measure is the default for test-share scenarios?
6. What candidate test-share defaults should be shown?
7. Which platform profiles are included in the first release?
8. What delivery thresholds are defaults versus user or agency inputs?
9. Which effectiveness sources are permitted to support a full spend-sufficiency conclusion?
10. How should uncertainty in CPA or elasticity be propagated into expected uplift?
11. Should the recommendation objective default to minimum spend, minimum test-market share or maximum power?
12. How should overlapping placebo windows be treated in empirical tail calculations?
13. Should exploratory fallback placebo windows be excluded?
14. Which residual diagnostics should contribute to Counterfactual Confidence?
15. Which Bayesian sampling profiles should be exposed?
16. Should saved experiment configurations be local files first or require persistent storage later?
17. What approval mechanism constitutes a frozen design in a single-user Streamlit application?
18. When should the temporary `TEST` prefix be removed?
19. What licensing model should be adopted?

## 25. Definition of done for the target product

GeoTestLab meets this PRD when:

- current matching, validation, impact and Bayesian workflows remain available;
- users can calculate power and minimum detectable effect for selected regional designs;
- users can compare market share, duration and spend scenarios;
- platform selection controls relevant media-delivery inputs;
- the product separates match quality, counterfactual credibility, power, delivery and effect plausibility;
- the product does not claim spend sufficiency without an effect bridge;
- the approved design can be frozen and reproduced;
- completed tests can be compared with the planned design;
- uncertainty and limitations are prominent;
- analytical logic is modular and typed;
- numerical changes are regression-protected;
- exports contain a complete experiment record;
- README, user, methodology and architecture documentation match the released product.

## 26. Source references used to scope this PRD

- `README.md`
- `PROJECT_DOCUMENTATION.md`
- `geotestmatch.py`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- merged pull requests through PR 17
- existing GeoTestLab Maintainability and UX Hardening Programme
- approved product-owner direction for a platform-agnostic power-analysis and test-sizing capability

