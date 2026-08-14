# GeoTestLab Decision Records

This directory holds analytical decision records (ADRs) for unresolved product
and methodology questions. No decision recorded here is approved yet.

The power-methodology pack is intentionally proposed rather than approved.
Its manual gate is [ADR-000](ADR-000-power-methodology-approval-gate.md): a
passing CI run or merged documentation PR cannot authorize production power
implementation.

The records below are **required future decision records** listed so the open
questions remain explicitly open. They are scaffold placeholders only; each
entry is marked `Pending` and no approved decision is implied.

## Required future decision records

| Record | Topic | Status |
|---|---|---|
| `ADR-000-power-methodology-approval-gate.md` | Manual product-owner approval gate for the production power core. | Pending approval |
| `ADR-001-power-method.md` | Primary power-analysis simulation method. | Proposed / pending approval |
| `ADR-002-detection-criterion.md` | Definition of what constitutes a detected effect. | Proposed / pending approval |
| `ADR-003-effect-injection-policy.md` | Relative versus absolute treatment-effect injection. | Proposed / pending approval |
| `ADR-004-placebo-finite-sample-policy.md` | Finite-sample and overlapping-window policy for placebo measures. | Proposed / pending approval |
| `ADR-005-exploratory-fallback-policy.md` | Treatment of exploratory fallback fits and safety scenarios. | Proposed / pending approval |
| `ADR-006-design-freeze-storage.md` | Persistence mechanism for approved design records (local serialisable record first; no database unless separately approved). | Pending |
| `ADR-007-experiment-versioning.md` | Versioning rules for experiment identity, input fingerprints and approved design versions. | Pending |
| `ADR-008-first-platform-profiles.md` | Which platform profiles are included in the first release of the test-sizing workflow. | Pending |
| `ADR-009-effectiveness-evidence-quality.md` | Which effectiveness-evidence sources are permitted to support a full spend-sufficiency conclusion. | Pending |
| `ADR-010-licensing.md` | Licensing model for the product. | Pending |
| `ADR-011-counterfactual-fit-policy.md` | Explicit OLS/Elastic Net/LASSO fit selection and fallback behaviour. | Proposed / pending approval |
| `ADR-012-effect-direction-policy.md` | One-sided and two-sided effect-direction policy. | Proposed / pending approval |
| `ADR-013-acceptance-criteria.md` | Calibration thresholds and scenario weighting. | Proposed / pending approval |
| `ADR-014-mde-policy.md` | MDE bounds, tolerance and not-reached semantics. | Proposed / pending approval |
| `ADR-015-production-simulation-count.md` | Production simulation count and reproducibility. | Proposed / pending approval |
| `ADR-016-scenario-grids.md` | Candidate market-share and duration grids. | Proposed / pending approval |
| `ADR-017-effect-shape.md` | Step, ramp, delayed and carryover effect shapes. | Proposed / pending approval |
| `ADR-018-minimum-history.md` | Frequency-aware minimum historical history. | Proposed / pending approval |
| `ADR-019-missingness-continuity.md` | Missingness, duplicate keys and time continuity rules. | Proposed / pending approval |
| `ADR-020-residual-autocorrelation.md` | Residual dependence and persistence handling. | Proposed / pending approval |
| `ADR-021-heteroskedasticity-policy.md` | Heteroskedasticity diagnostics and treatment. | Proposed / pending approval |
| `ADR-022-power-uncertainty.md` | Conditional and unconditional power uncertainty. | Proposed / pending approval |

## Rules

- Each ADR, once drafted, must record the decision, rationale, alternatives
  considered, affected requirements and implementation status.
- No ADR may be marked as approved without explicit product-owner approval.
- The product owner must record the approved methodology version, ADR IDs,
  identity, timestamp, reviewed evidence commit and conditions in ADR-000.
- Production power work must not start while ADR-000 has
  `approval_status: pending`.
- Do not create fabricated approved decisions.
