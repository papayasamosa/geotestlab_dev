# GeoTestLab PRD Traceability and Delivery Roadmap

**Document type:** Scope reconciliation, requirement traceability and delivery plan  
**Parent document:** `PRD.md`  
**Version:** 1.3
**Date:** 15 August 2026

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
- Commit: `f3810f848932d52b4b02267cd1641c6fb53ef051`
- Current application source: `geotestmatch.py` (thin adapters and UI)
- Extracted packages: `geotestlab/data/`, `geotestlab/matching/`,
  `geotestlab/validation/`, `geotestlab/bayesian/`,
  `geotestlab/experiment/`, `geotestlab/power/`,
  `geotestlab/media/`, `geotestlab/effect/` and
  `geotestlab/recommendation/`
- Current workflow: eight Streamlit tabs, including power, delivery,
  effect-plausibility and integrated recommendation
- Current product documentation: `README.md`, the product pack and the user,
  methodology and architecture guides

## 4. Reconciliation of the older hardening PRD

The maintainability PRD was accurate as a proposed programme on 27 July 2026, but several problem statements are now outdated as of the reviewed baseline.

| Earlier stated gap | Current repository status | Treatment in new plan |
|---|---|---|
| No visible automated regression suite | Implemented through fast tests and numerical golden scenarios | Record as current baseline and continue expanding |
| No CI pipeline | Implemented with test, lock and numerical jobs | Record as current baseline |
| Installation not reproducible | Python 3.11, `pyproject.toml`, runtime and dev lock files, lock verification implemented | Record as current baseline |
| No structured data-quality report | Typed report, UI, blockers and downloads implemented | Record as current baseline |
| Guided search not deterministic | Explicit seed and deterministic constraints implemented | Record as current baseline |
| Matching logic concentrated in monolith | Matching core extracted into Streamlit-free package | Resolved |
| Results represented through large untyped dictionaries | Typed result contracts now cover the matching, validation, Bayesian and experiment cores; untyped dicts remain only at the app adapter boundary | Mostly resolved |
| Session-state invalidation distributed | Stage fingerprints and stage-scoped staleness exist, but no complete workflow state model | Retain as partially implemented |
| README insufficient | README plus user, methodology and architecture guides now document the implemented workflow | Resolved for the current workflow; continue updating with releases |
| Interface exposes too much at once | Still relevant | Retain as UX requirement |
| Validation and Bayesian logic tightly coupled to UI | Validation and Bayesian domain logic extracted into Streamlit-free packages; the app keeps thin adapters | Mostly resolved (the UI itself remains a monolith) |

### 4.1 Delivered foundations versus complete contracts

Several capabilities are delivered as **foundations** but are not yet the
**complete product contract**. The distinction matters for scope control:

- **Experiment foundations vs the complete FR-16 contract.**
  `geotestlab/experiment/` delivers experiment identity, stage fingerprints,
  stage-scoped staleness and immutable frozen design versions. The complete
  FR-16 "approved design freeze" (approval timestamp, power result and MDE in
  the frozen record, platform and campaign setup, budget and delivery
  assumptions, effect-plausibility assumptions, analyst notes) is not yet
  delivered.
- **Unified local export vs the complete FR-22 export.** The app now exports a
  local JSON experiment record with compact validation, power, delivery,
  effect-plausibility and recommendation summaries. Approved-design
  persistence, package metadata and stakeholder-specific views remain planned.
- **Evidence harness vs production methodology.** `geotestlab/power/` contains
  both the production selected-design contract and the separate methodology
  evidence harness. ADR-000 governs the evidence conditions; the production
  contract preserves explicit support and method statuses.
- **Reduced-sampling smoke vs Bayesian assurance.** The Bayesian CI job runs a
  reduced-sampling execution-path smoke test (tiny draws/tune/chains) to prove
  the pipeline runs; it is **not** evidence of production MCMC convergence or
  assurance.
- **Extracted domain logic vs complete UI separation.** Domain logic is
  extracted into Streamlit-free packages behind thin adapters, but the
  Streamlit application script remains a single monolith; full UI
  modularisation is a separate, later concern.

## 5. Requirement traceability matrix

| Product area | Current capability | Canonical PRD requirement | Status | Primary next action |
|---|---|---|---|---|
| Market setup | Workbook-driven markets and geography levels | FR-1 | Current | Improve documentation and data-version metadata |
| Custom geographies | KPI Pattern upload | FR-1, FR-3 | Current | Preserve and improve mapping guidance |
| KPI ingestion | Simple and aggregated Excel, with canonical regional preparation and provenance | FR-2 | Current / strengthened | Reuse the contract across validation and power sizing |
| Data quality | Typed report, blockers, rejected/unmapped downloads | FR-2 | Current | Add experiment-level quality summary |
| Structural matching | Demographic and population features | FR-3 to FR-5 | Current | Preserve behaviour during refactor |
| KPI Pattern matching | Indexed historical KPI shape | FR-3 to FR-5 | Current | Clarify terminology in methodology guide |
| Manual design | Pick both groups | FR-4 | Current | Add approved-design freeze |
| Automated design | Pick test or auto-build groups | FR-4 | Current | Integrate candidate power scenarios |
| Region constraints | Include/exclude and global exclusion | FR-4 | Current | Reuse typed constraint model in sizing |
| Match strategies | Greedy, hill climbing, stochastic | FR-5 | Current | Finalise user-facing strategy naming |
| Match diagnostics | Distance, SMD, feature detail | FR-5 | Current | Add design summary hierarchy |
| KPI validation | Elastic Net and LASSO methods via `geotestlab/validation/` | FR-6 | Current | Strengthen adapters and schemas |
| Frequency handling | Weekly/daily and mismatch gate via typed `FrequencyConfig` | FR-6 | Current | Extend to further frequencies |
| Lagged controls | Frequency-aware | FR-6, FR-18 | Current | Preserve calendar-continuity rules |
| Rolling validation | Error, bias, overfitting with typed `RollingOriginDiagnostics` | FR-7 | Current | Extend typed diagnostics |
| Residual diagnostics | Durbin-Watson | FR-7 | Current | Decide additional diagnostics |
| Placebos | Capped historical windows | FR-8 | Current | Approve finite-sample and fallback policy (recorded in the power-methodology spike) |
| Counterfactual Confidence | Priority cascade | FR-9 | Current | Review thresholds and driver logic |
| Prospective power | Approved production contract, selected-design UI and typed matched/validated candidate pipeline; evidence harness remains separate | FR-10, FR-11 | Current / strengthened | Expose complete candidate-grid UX |
| Platform selector | Generic profile schema, registered Meta profile and dedicated Meta UI | FR-12 | Current for Meta | Keep broader profile policy pending and add profiles later |
| Delivery feasibility | Profile-driven calculations, thresholds and dedicated UI for Meta | FR-13 | Current for Meta | Add further profiles and production delivery integrations later |
| Effect plausibility | Typed evidence/scenario layer with MDE comparison | FR-14 | Current / strengthened | Keep evidence hierarchy pending and link scenarios to recommendation |
| Integrated recommendation | Separate gate comparison, explicit objective, limiting factors and override rationale | FR-15 | Partially integrated | Consume typed upstream scenario, validation, power, delivery and effect results |
| Design freeze | Versioned frozen-design foundations (immutable versions, fingerprints) | FR-16 | Partially implemented | Complete the FR-16 approved-design-freeze contract |
| Impact measurement | Actual/counterfactual and uplift | FR-17 | Current | Link to approved design |
| Bayesian TBR | Core extracted into `geotestlab/bayesian/`; reduced-sampling smoke CI | FR-18 | Current | Bayesian assurance (production sampling quality) |
| Result hierarchy | Partial | FR-19 | Partially implemented | Redesign top-level summary |
| Workflow state | Stage fingerprints + stage-scoped staleness (experiment foundations) | FR-20 | Partially implemented | Complete workflow state model |
| Guided UX | Some help and expanders | FR-21 | Partially implemented | Introduce stage-based guidance |
| Exports | Local JSON experiment-record export with unified validation, power, delivery, effect and recommendation summaries | FR-22 | Partially implemented | Add approved-design persistence, package metadata, reload and stakeholder views |
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

- adopt canonical PRD (delivered);
- reconcile current documentation (delivered);
- keep numerical regression gates required;
- finish validation and Bayesian extraction (delivered);
- add typed result contracts (delivered for the matching, validation, Bayesian and experiment cores);
- implement complete fingerprints and stale-state behaviour (foundations delivered in `geotestlab/experiment/`).

### P1. Prospective test design

- power-analysis methodology spike and ADR pack (delivered; methodology
  approved under ADR-000);
- selected-design power and MDE (delivered);
- future campaign schedule versus historical power-horizon contract (delivered in PR2);
- matched and validated candidate market-share and duration scenarios (delivered in PR3);
- design-level export and complete approved design freeze.

### P1. Media feasibility

- Meta profile selector and common campaign inputs (delivered);
- spend-to-delivery calculations and thresholds (delivered for Meta);
- typed delivery results consumed by candidate scenarios;
- broader platform profiles only after the Meta flow is coherent.

### P1. Effect plausibility

- evidence/scenario contract, provenance and MDE comparison (delivered);
- pending evidence-quality policy;
- typed effect results consumed by candidate recommendation.

### P2. Product experience and reporting

- stage-based workflow status;
- result hierarchy;
- stakeholder summary;
- complete experiment export (the local JSON foundation and unified summaries
  are delivered; package metadata, safe reload and stakeholder views remain);
- accessible narrow-screen behaviour;
- saved configuration loading.

The next implementation sequence is deliberately dependency-ordered:

1. reconcile product documentation (delivered in PR1);
2. fix the prospective power horizon contract (delivered in PR2);
3. complete matched candidate construction (delivered in PR3);
4. expose scenario sizing in the Power & Test Sizing UI;
5. integrate typed upstream recommendation evidence;
6. reorder and guide the lifecycle UX;
7. complete approved-design freeze;
8. strengthen reproducibility and reload;
9. add end-to-end planning and accessibility assurance;
10. perform release-readiness cleanup.

### P2. Additional methodology

- additional residual diagnostics;
- alternative effect shapes;
- Bayesian assurance (the reduced-sampling smoke test is not assurance);
- non-negative outcome models;
- expanded platform profiles.

## 8. Proposed implementation milestones

## Milestone 0. PRD adoption and documentation reconciliation

**Status:** Delivered (PR `docs/canonical-product-prd`).

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

**Status:** Delivered (PR `refactor/validation-core`).

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

**Status:** Delivered (PR `refactor/bayesian-core`). A reduced-sampling smoke test is part of CI; Bayesian assurance (production sampling quality) remains pending.

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

**Status:** Partially delivered — experiment identity, fingerprints, staleness and frozen-design foundations exist (PR `feature/experiment-identity-and-freeze`); the complete workflow state model and experiment summary are pending.

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

**Status:** Delivered as an evidence-strengthened spike; the methodology ADR
pack is approved under
`docs/product/decisions/ADR-000-power-methodology-approval-gate.md`, and the
production power core is now the active next stage under those conditions.

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

**Status:** Delivered for the selected-design workflow after explicit
product-owner methodology approval; implementation preserves the approved
method/version and support-status conditions. The backend now constructs
matched and historically validated candidates with retained provenance and
blockers; the candidate-grid UX remains follow-on work.

### Deliverables

- selected-design power;
- MDE;
- candidate market-share and duration scenario contracts;
- result table and charts;
- staleness and export;
- automated tests.

### Exit criteria

- user can identify a powered regional design without media inputs;
- results are reproducible;
- insufficient-data cases are actionable.

## Milestone 6. Platform-aware media feasibility

**Status:** Platform-profile schema and Meta delivery-feasibility stage delivered;
broader profiles and production integrations remain planned.

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

**Status:** Partially integrated for the current workflow. Effect plausibility,
typed integrated recommendation and unified export are implemented; normal
recommendation operation still needs upstream candidate results, while the
evidence-quality policy and recommendation objective remain pending product
decisions.

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

**Status:** In progress — user, methodology and architecture guides now cover
the released workflow; approved design freeze, accessibility review and
production release work remain.

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

Items 1–13 below are delivered on `main` as of the reviewed baseline, with the
remaining product decisions and production-readiness work called out below.

1. `docs/canonical-product-prd` — delivered
2. `refactor/validation-core` — delivered
3. `refactor/bayesian-core` — delivered
4. `feature/experiment-identity-and-freeze` — delivered (foundations)
5. `spike/power-analysis-methodology` — delivered; methodology pack approved
6. `feature/power-analysis-core` — delivered
7. `feature/power-analysis-ui` — delivered
8. `feature/platform-profile-schema` — delivered
9. `feature/media-delivery-feasibility` — delivered
10. `feature/effect-plausibility-scenarios` — delivered
11. `feature/integrated-design-recommendation` — delivered
12. `feature/unified-experiment-export` — delivered, including export
    reconciliation follow-ups
13. `docs/user-and-methodology-guides` — delivered

Each analytical PR should be small enough to review and should include tests, documentation and explicit numerical change notes where applicable.

### 9.1 Next dependency-ordered sequence

The next work is intentionally sequenced from the current baseline rather than
stacked on unmerged branches:

1. reconcile current product documentation (delivered in PR1);
2. fix the prospective power horizon contract (delivered in PR2);
3. complete matched candidate design construction (delivered in PR3);
4. expose scenario sizing in the Power & Test Sizing UI;
5. replace manual recommendation evidence with typed upstream candidates;
6. reorder and guide lifecycle navigation;
7. complete approved-design freeze;
8. strengthen reproducibility and experiment reload;
9. add deterministic end-to-end planning and accessibility assurance;
10. complete release-readiness cleanup.

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

1. Decide the recommendation optimisation objective and effectiveness
   evidence-quality policy recorded in the pending ADRs.
2. Complete the FR-16 approved-design-freeze record and persistence workflow.
3. Add broader platform profiles and production delivery integrations.
4. Extend FR-22 exports with package/version metadata, approved-design
   persistence and stakeholder-specific views.
5. Complete accessibility, responsive-workflow and release-readiness review.
6. Continue behaviour-preserving modularisation; full UI modularisation is a
   separate, later concern.

