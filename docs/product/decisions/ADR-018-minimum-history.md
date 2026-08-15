# ADR-018: Historical data minimum

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

The current candidate minimum is **104 retained weekly periods** for the AR(1)
method. Fewer periods must block the relevant power result rather than produce
a low-confidence number. The minimum must be frequency-aware and may be
raised when the approved method or diagnostics require it.

## Current evidence

`weekly_52` is blocked in the v2.1 suite. The suite also contains `weekly_104`
and `weekly_156`, so the decision is visible across history lengths, but the
aggregate study still fails calibration thresholds.

## Affected requirements and implementation status

FR-6, FR-7 and FR-10. The production contract carries the minimum-history and
frequency-aware safety checks as support/blocker conditions; this ADR does not
claim that the evidence establishes adequacy for every KPI or history length.
