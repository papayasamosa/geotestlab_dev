# ADR-005: Exploratory fallback and safety policy

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

Fallback fits and fallback placebo windows may be used for exploratory
diagnostics, but never silently support a formal power or recommendation
result. A fallback must be recorded with its reason, fit method, and support
status; a blocked or unsupported case must remain visible to the analyst.

The additional scenarios `irrelevant_controls_market`,
`nonlinear_counterfactual_market`, and `structural_break_market` remain
evidence-only until their safety treatment is explicitly approved.

## Current evidence

The v2.1 summary reports fallback rate **0%** and additional safety coverage
**21/25 = 84%**. Four structural-break seeds are blocked by persistence but
are not yet classified as expected blocks. This is an unresolved limitation,
not a reason to relax the safety policy.

## Affected requirements and implementation status

FR-7, FR-9, FR-10 and FR-11. The policy is documented and tested in the spike;
production status semantics remain gated.
