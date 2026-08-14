# GeoTestLab Decision Records

This directory holds analytical decision records (ADRs) for unresolved product
and methodology questions. The power-methodology records below were approved
by the product owner as recorded in ADR-000; unrelated product decisions remain
pending.

The power-methodology pack's manual gate is
[ADR-000](ADR-000-power-methodology-approval-gate.md). A passing CI run or
merged documentation PR could not authorize production power implementation;
the gate is now satisfied by the explicit product-owner approval recorded in
that ADR.

The records below are **required future decision records** listed so the open
questions remain explicitly open. They are scaffold placeholders only; each
entry is marked `Pending` and no approved decision is implied.

## Required future decision records

| Record | Topic | Status |
|---|---|---|
| `ADR-000-power-methodology-approval-gate.md` | Manual product-owner approval gate for the production power core. | Approved |
| `ADR-001-power-method.md` | Primary power-analysis simulation method. | Approved — explicit method required; no implicit primary default |
| `ADR-002-detection-criterion.md` | Definition of what constitutes a detected effect. | Approved |
| `ADR-003-effect-injection-policy.md` | Relative versus absolute treatment-effect injection. | Approved |
| `ADR-004-placebo-finite-sample-policy.md` | Finite-sample and overlapping-window policy for placebo measures. | Approved |
| `ADR-005-exploratory-fallback-policy.md` | Treatment of exploratory fallback fits and safety scenarios. | Approved |
| `ADR-006-design-freeze-storage.md` | Persistence mechanism for approved design records (local serialisable record first; no database unless separately approved). | Pending |
| `ADR-007-experiment-versioning.md` | Versioning rules for experiment identity, input fingerprints and approved design versions. | Pending |
| `ADR-008-first-platform-profiles.md` | Which platform profiles are included in the first release of the test-sizing workflow. | Pending — proposed generic schema with Meta profile |
| `ADR-009-effectiveness-evidence-quality.md` | Which effectiveness-evidence sources are permitted to support a full spend-sufficiency conclusion. | Pending |
| `ADR-010-licensing.md` | Licensing model for the product. | Pending |
| `ADR-011-counterfactual-fit-policy.md` | Explicit OLS/Elastic Net/LASSO fit selection and fallback behaviour. | Approved |
| `ADR-012-effect-direction-policy.md` | One-sided and two-sided effect-direction policy. | Approved |
| `ADR-013-acceptance-criteria.md` | Calibration thresholds and scenario weighting. | Approved |
| `ADR-014-mde-policy.md` | MDE bounds, tolerance and not-reached semantics. | Approved |
| `ADR-015-production-simulation-count.md` | Production simulation count and reproducibility. | Approved |
| `ADR-016-scenario-grids.md` | Candidate market-share and duration grids. | Approved |
| `ADR-017-effect-shape.md` | Step, ramp, delayed and carryover effect shapes. | Approved |
| `ADR-018-minimum-history.md` | Frequency-aware minimum historical history. | Approved |
| `ADR-019-missingness-continuity.md` | Missingness, duplicate keys and time continuity rules. | Approved |
| `ADR-020-residual-autocorrelation.md` | Residual dependence and persistence handling. | Approved |
| `ADR-021-heteroskedasticity-policy.md` | Heteroskedasticity diagnostics and treatment. | Approved |
| `ADR-022-power-uncertainty.md` | Conditional and unconditional power uncertainty. | Approved |

## Rules

- Each ADR, once drafted, must record the decision, rationale, alternatives
  considered, affected requirements and implementation status.
- No ADR may be marked as approved without explicit product-owner approval
  recorded in ADR-000.
- The product owner must record the approved methodology version, ADR IDs,
  identity, timestamp, reviewed evidence commit and conditions in ADR-000.
- Production power work may start only while ADR-000 has
  `approval_status: approved` and the approved methodology version is carried
  into the implementation contract.
- Do not create fabricated approved decisions.
