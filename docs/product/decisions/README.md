# GeoTestLab Decision Records

This directory will hold analytical decision records (ADRs) for unresolved
product and methodology questions. No decision recorded here is approved yet.

The records below are **required future decision records** listed so the open
questions remain explicitly open. They are scaffold placeholders only; each
entry is marked `Pending` and no approved decision is implied.

## Required future decision records

| Record | Topic | Status |
|---|---|---|
| `ADR-001-power-method.md` | Primary power-analysis simulation method (historical residual simulation, effect injection into held-out windows, model-based counterfactual simulation, or bootstrap/placebo-based empirical power). | Pending |
| `ADR-002-detection-criterion.md` | Definition of what constitutes a detected effect (interval excludes zero, empirical placebo threshold, sign-and-threshold rule, or posterior-probability threshold). | Pending |
| `ADR-003-effect-injection-policy.md` | Treatment-effect injection policy for power simulations (relative vs. absolute, effect shape, ramp-up, delayed start, decay or carryover). | Pending |
| `ADR-004-placebo-finite-sample-policy.md` | Finite-sample and overlapping-window policy for placebo-based empirical tail measures. | Pending |
| `ADR-005-exploratory-fallback-policy.md` | Treatment of exploratory fixed-alpha fallback fits (and fallback placebo windows) in formal conclusions. | Pending |
| `ADR-006-design-freeze-storage.md` | Persistence mechanism for approved design records (local serialisable record first; no database unless separately approved). | Pending |
| `ADR-007-experiment-versioning.md` | Versioning rules for experiment identity, input fingerprints and approved design versions. | Pending |
| `ADR-008-first-platform-profiles.md` | Which platform profiles are included in the first release of the test-sizing workflow. | Pending |
| `ADR-009-effectiveness-evidence-quality.md` | Which effectiveness-evidence sources are permitted to support a full spend-sufficiency conclusion. | Pending |
| `ADR-010-licensing.md` | Licensing model for the product. | Pending |

## Rules

- Each ADR, once drafted, must record the decision, rationale, alternatives
  considered, affected requirements and implementation status.
- No ADR may be marked as approved without explicit product-owner approval.
- Do not create fabricated approved decisions.
