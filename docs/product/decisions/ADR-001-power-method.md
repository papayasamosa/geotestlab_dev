# ADR-001: Primary power-analysis simulation method

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14
- **Evidence:** `power-methodology-evidence-v2-summary.json`, scenario suite 2.1.0

## Decision proposal

Do not select an implicit primary production simulation method. Keep the
choice explicit between `model_simulation` and `residual_simulation` while the
remaining calibration limitations are carried into support status. Keep
`placebo_empirical` as a cross-check, not as the production absolute-power
engine.

This is a deliberate deferral, not permission to choose the method in code.
The next evidence iteration must compare methods by scenario, fit policy,
calibration, safety coverage, uncertainty and runtime.

## Current evidence

The committed v2.1 study covers 1,080 core runs (5 data seeds × 3 simulation
seeds × 2 methods × 3 fit methods). It reports mean absolute power bias **0.102**,
worst supported bias **0.477**, false-supported rate **18/540 = 3.3%**, and
seed-sensitivity power standard deviation **0.084**. The proposed thresholds
are 0.05, 0.15, 0%, and 0.05 respectively; therefore the evidence does not
support approval.

## Alternatives considered

- Select `model_simulation` because it preserves the fitted counterfactual
  structure.
- Select `residual_simulation` because moving blocks retain short-range
  dependence.
- Select placebo empirical power as primary.
- Defer the choice until supported-scenario calibration is acceptable.

The fourth alternative is the approved policy in this ADR. The evidence does
not establish a safe universal winner, and placebo windows do not provide an
independent prospective null for absolute power. A production caller must
therefore choose and record the method explicitly.

## Affected requirements and implementation status

This affects FR-10 and FR-11. No production implementation is authorised;
the current package remains a spike under `geotestlab/power/`.
