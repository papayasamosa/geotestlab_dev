# ADR-020: Residual and autocorrelation handling

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

The approved method must diagnose residual autocorrelation and propagate the
approved dependence model into simulation. For AR(1), the fitted persistence,
innovation scale, history sufficiency and safety status must be recorded. A
near-unit-root or otherwise unsupported process blocks power rather than being
clipped into a convenient parameter.

The residual-simulation candidate uses a circular moving-block bootstrap to
retain short-range dependence. Model-simulation parameter uncertainty remains
an open calibration question.

## Current evidence

`high_autocorrelation` and `weekly_52` are blocked in the v2.1 suite. The
stronger persistence gate is evidence-informed but the study does not yet
support approval of the full production uncertainty treatment.

## Affected requirements and implementation status

FR-6, FR-7 and FR-10. No production autocorrelation default is approved.
