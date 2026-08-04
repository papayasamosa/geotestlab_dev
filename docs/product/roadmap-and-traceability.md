# GeoTestLab PRD Traceability and Delivery Roadmap

**Document type:** Scope reconciliation, requirement traceability and delivery plan  
**Parent document:** `PRD.md`  
**Version:** 1.0  
**Date:** 4 August 2026  

## 1. Purpose

This document reconciles:

- current repository behaviour;
- the existing project documentation;
- the earlier maintainability and UX hardening PRD;
- the new canonical product PRD; and
- the proposed power-analysis and test-sizing capability.

It prevents two common problems when creating a PRD after the product already exists:

1. describing implemented functionality as if it were still hypothetical; and
2. copying old gaps into the new plan even though repository work has already resolved them.

## 2. Source-of-truth hierarchy

When sources conflict, use this order:

1. approved product decisions and the canonical PRD;
2. current production code and tests on `main`;
3. current methodology and architecture documentation;
4. merged pull-request descriptions for recently completed work;
5. older planning documents.

The current production code remains the source of truth for existing behaviour until a deliberate change is approved and merged.

## 3. Baseline reviewed

- Repository: `papayasamosa/geotestlab_dev`
- Branch: `main`
- Commit: `c532625b3d7356e344138fcd9211f8ad25c71d3c`
- Current application source: `geotestmatch.py`
- Extracted packages: `geotestlab/data/` and `geotestlab/matching/`
- Current workflow: four Streamlit tabs
- Current product documentation: `README.md` and `PROJECT_DOCUMENTATION.md`

## 4. Reconciliation of the older hardening PRD

The maintainability PRD was accurate as a proposed programme on 27 July 2026, but several problem statements are now outdated as of the reviewed baseline.

| Earlier stated gap | Current repository status | Treatment in new plan |
|---|---|---|
| No visible automated regression suite | Implemented through fast tests and numerical golden scenarios | Record as current baseline and continue expanding |
| No CI pipeline | Implemented with test, lock and numerical jobs | Record as current baseline |
| Installation not reproducible | Python 3.11, `pyproject.toml`, runtime and dev lock files, lock verification implemented | Record as current baseline |
| No structured data-quality report | Typed report, UI, blockers and downloads implemented | Record as current baseline |
| Guided search not deterministic | Explicit seed and deterministic constraints implemented | Record as current baseline |
| Matching logic concentrated in monolith | Matching core extracted into Streamlit-free package | Mark partially resolved |
| Results represented through large untyped dictionaries | Still true for substantial validation and Bayesian areas | Retain as planned work |
| Session-state invalidation distributed | Some staleness handling exists, but no complete workflow state model | Retain as partially implemented |
| README insufficient | Substantially improved, but full user and methodology docs remain incomplete | Retain as partial documentation gap |
| Interface exposes too much at once | Still relevant | Retain as UX requirement |
| Validation and Bayesian logic tightly coupled to UI | Still relevant | Retain as engineering priority |

## 5. Requirement traceability matrix

| Product area | Current capability | Canonical PRD requirement | Status | Primary next action |
|---|---|---|---|---|
| Market setup | Workbook-driven markets and geography levels | FR-1 | Current | Improve documentation and data-version metadata |
| Custom geographies | KPI Pattern upload | FR-1, FR-3 | Current | Preserve and improve mapping guidance |
| KPI ingestion | Simple and aggregated Excel | FR-2 | Current | Extract remaining adapters and strengthen schemas |
| Data quality | Typed report, blockers, rejected/unmapped downloads | FR-2 | Current | Add experiment-level quality summary |
| Structural matching | Demographic and population features | FR-3 to FR-5 | Current | Preserve behaviour during refactor |
| KPI Pattern matching | Indexed historical KPI shape | FR-3 to FR-5 | Current | Clarify terminology in methodology guide |
| Manual design | Pick both groups | FR-4 | Current | Add approved-design freeze |
| Automated design | Pick test or auto-build groups | FR-4 | Current | Integrate candidate power scenarios |
| Region constraints | Include/exclude and global exclusion | FR-4 | Current | Reuse typed constraint model in sizing |
| Match strategies | Greedy, hill climbing, stochastic | FR-5 | Current | Finalise user-facing strategy naming |
| Match diagnostics | Distance, SMD, feature detail | FR-5 | Current | Add design summary hierarchy |
| KPI validation | Elastic Net and LASSO methods | FR-6 | Current | Extract pure validation services |
| Frequency handling | Weekly/daily and mismatch gate | FR-6 | Current | Move into typed config |
| Lagged controls | Frequency-aware | FR-6, FR-18 | Current | Preserve calendar-continuity rules |
| Rolling validation | Error, bias, overfitting | FR-7 | Current | Extract and type results |
| Residual diagnostics | Durbin-Watson | FR-7 | Current | Decide additional diagnostics |
| Placebos | Capped historical windows | FR-8 | Current | Approve finite-sample and fallback policy |
| Counterfactual Confidence | Priority cascade | FR-9 | Current | Review thresholds and driver logic |
| Prospective power | None | FR-10, FR-11 | Planned | Methodology spike and MVP |
| Platform selector | None | FR-12 | Planned | Define first platform profiles |
| Delivery feasibility | None | FR-13 | Planned | Build profile-driven inputs and calculations |
| Effect plausibility | None | FR-14 | Planned | Define evidence hierarchy and scenarios |
| Integrated recommendation | Matching recommendations only | FR-15 | Planned | Build after power and delivery layers |
| Design freeze | Run snapshots, no formal approved version | FR-16 | Planned | Create versioned experiment record |
| Impact measurement | Actual/counterfactual and uplift | FR-17 | Current | Link to approved design |
| Bayesian TBR | PyMC analysis and diagnostics | FR-18 | Current | Extract core and add sampling profiles |
| Result hierarchy | Partial | FR-19 | Partially implemented | Redesign top-level summary |
| Workflow state | Matching and validation staleness | FR-20 | Partially implemented | Create workflow state model |
| Guided UX | Some help and expanders | FR-21 | Partially implemented | Introduce stage-based guidance |
| Exports | Multiple exports, not one experiment record | FR-22 | Partially implemented | Unified reproducible export |
| Error handling | Some domain errors and technical expanders | FR-23 | Partially implemented | Complete domain exception boundary |
| Accessibility | Theme and focus improvements | FR-24 | Partially implemented | Full keyboard and zoom review |

## 6. Recommended document structure in the repository

```text
docs/
  product/
    PRD.md
    power-analysis-and-test-sizing.md
    roadmap-and-traceability.md
    decisions/
      ADR-001-power-method.md
      ADR-002-placebo-finite-sample-policy.md
      ADR-003-design-freeze-storage.md
  user/
    getting-started.md
    design-a-test.md
    evaluate-a-test.md
    interpret-results.md
  methodology/
    matching.md
    validation.md
    power-analysis.md
    placebo-analysis.md
    bayesian-tbr.md
    limitations.md
  architecture/
    overview.md
    data-flow.md
    state-and-fingerprints.md
```

The root README should remain a concise installation and orientation document, linking to this documentation rather than attempting to contain the whole product definition.

## 7. Delivery priorities

### P0. Product governance and behaviour safety

- adopt canonical PRD;
- reconcile current documentation;
- keep numerical regression gates required;
- finish validation and Bayesian extraction;
- add typed result contracts;
- implement complete fingerprints and stale-state behaviour.

### P1. Prospective test design

- power-analysis methodology spike;
- selected-design power and MDE;
- market-share and duration scenarios;
- design-level export;
- approved design freeze.

### P1. Media feasibility

- platform selector;
- common campaign inputs;
- Meta and agreed first platform profiles;
- spend-to-delivery calculations;
- delivery thresholds;
- scenario comparison.

### P1. Effect plausibility

- evidence hierarchy;
- effectiveness scenarios;
- expected KPI effect versus MDE;
- conditional recommendation.

### P2. Product experience and reporting

- stage-based workflow status;
- result hierarchy;
- stakeholder summary;
- complete experiment export;
- accessible narrow-screen behaviour;
- saved configuration loading.

### P2. Additional methodology

- additional residual diagnostics;
- alternative effect shapes;
- Bayesian assurance;
- non-negative outcome models;
- expanded platform profiles.

## 8. Proposed implementation milestones

## Milestone 0. PRD adoption and documentation reconciliation

### Deliverables

- canonical PRD committed;
- power-analysis specification committed;
- roadmap and traceability committed;
- README links updated;
- older hardening PRD relabelled as engineering companion;
- project documentation marked with current review commit.

### Exit criteria

- one clear product source of truth;
- current and planned features visibly separated;
- no known outdated architecture claim remains unlabelled.

## Milestone 1. Validation-core extraction

### Deliverables

- typed validation configuration and result;
- pure model-matrix service;
- regularised model service;
- rolling-origin module;
- placebo module;
- Counterfactual Confidence module;
- compatibility adapter in Streamlit.

### Exit criteria

- no Streamlit imports in validation core;
- existing numerical goldens pass unchanged or approved differences are recorded;
- all validation methods use typed outputs.

## Milestone 2. Bayesian-core extraction

### Deliverables

- typed Bayesian configuration and result;
- model builder;
- posterior summariser;
- predictive-interval service;
- diagnostic service;
- serialisable summary separated from trace object.

### Exit criteria

- baseline derived quantities within approved tolerance;
- AR(1) and non-AR(1) scenarios tested;
- no result-only rerun of sampling.

## Milestone 3. Workflow state and experiment identity

### Deliverables

- experiment identity;
- workflow state model;
- deterministic fingerprints;
- frozen design record;
- versioning and stale-state rules;
- experiment summary.

### Exit criteria

- all material changes invalidate the correct downstream stages;
- approved designs cannot be silently overwritten;
- exports contain experiment identity.

## Milestone 4. Power-analysis methodology prototype

### Deliverables

- methodological decision record;
- prototype simulation engine;
- synthetic validation cases;
- sensitivity report;
- performance profile;
- proposed UI outputs.

### Exit criteria

- method produces expected results on hand-calculable or controlled synthetic cases;
- limitations are documented;
- product owner approves detection criterion and defaults.

## Milestone 5. Power-analysis MVP

### Deliverables

- selected-design power;
- MDE;
- candidate market-share scenarios;
- duration scenarios;
- result table and charts;
- staleness and export;
- automated tests.

### Exit criteria

- user can identify a powered regional design without media inputs;
- results are reproducible;
- insufficient-data cases are actionable.

## Milestone 6. Platform-aware media feasibility

### Deliverables

- platform profile schema;
- selector and dynamic form;
- common campaign fields;
- first approved profiles;
- delivery calculations and thresholds;
- supplied-versus-calculated labels.

### Exit criteria

- Meta is supported as a profile, not a special-case product;
- at least one non-Meta platform profile passes acceptance tests;
- missing forecast inputs are clearly identified.

## Milestone 7. Effect plausibility and spend recommendation

### Deliverables

- effectiveness evidence model;
- scenario assumptions;
- expected KPI effect;
- comparison with MDE;
- integrated recommendation;
- limiting-factor explanation;
- override workflow.

### Exit criteria

- full and conditional recommendations are clearly different;
- no conclusion is produced without required evidence;
- recommendation is reproducible and exportable.

## Milestone 8. Reporting and production readiness

### Deliverables

- stakeholder summary;
- technical analysis record;
- planned-versus-analysed comparison;
- user and methodology documentation;
- accessibility review;
- performance baseline;
- production naming and licence decision.

### Exit criteria

- end-to-end workflow meets the core PRD definition of done;
- documentation matches released behaviour;
- release can be recreated from source and locks.

## 9. Suggested pull-request sequence for the new capability

1. `docs/canonical-product-prd`
2. `refactor/validation-core`
3. `refactor/bayesian-core`
4. `feature/experiment-identity-and-freeze`
5. `spike/power-analysis-methodology`
6. `feature/power-analysis-core`
7. `feature/power-analysis-ui`
8. `feature/platform-profile-schema`
9. `feature/media-delivery-feasibility`
10. `feature/effect-plausibility-scenarios`
11. `feature/integrated-design-recommendation`
12. `feature/unified-experiment-export`
13. `docs/user-and-methodology-guides`

Each analytical PR should be small enough to review and should include tests, documentation and explicit numerical change notes where applicable.

## 10. Decision log required

Before implementation begins, create decision records for:

- initial power method;
- detection criterion;
- effect injection;
- placebo finite-sample policy;
- exploratory fallback treatment;
- first platform profiles;
- effectiveness evidence quality;
- recommendation optimisation objective;
- design-freeze persistence;
- experiment versioning;
- licensing.

## 11. PRD maintenance process

The PRD should change when:

- product scope changes;
- a major methodology decision is approved;
- a planned capability is removed or materially altered;
- user workflow changes;
- a new platform class introduces a new product concept.

The PRD should not be updated merely because an internal function or module name changes without product impact.

Every PRD change should include:

- version increment;
- change summary;
- affected requirements;
- implementation status update;
- linked decision record where relevant.

## 12. Immediate next actions

1. Review and approve the canonical product framing.
2. Decide whether power analysis is a dedicated top-level stage or a section within Validate Test Design.
3. Approve a methodology spike before committing to a numerical implementation.
4. Commit the PRD pack to `docs/product/`.
5. Update `PROJECT_DOCUMENTATION.md` to distinguish current implementation documentation from future product requirements.
6. Continue the existing behaviour-preserving modularisation before adding the power engine directly to the monolith.

