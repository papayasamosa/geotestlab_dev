# ADR-004: Placebo finite-sample and overlap policy

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Placebo windows are a diagnostic cross-check and must use retained,
date-aligned, non-overlapping pre-period windows. The service must require a
minimum of five valid placebo windows, report the number retained, and return
an explicit incomplete result when the minimum is not met. It must never pad
an empty or short placebo sample with fabricated zeroes.

## Rationale and limitations

The prototype implements this policy and records placebo results separately.
Placebo windows are finite and not independent prospective draws, so they do
not by themselves establish absolute power calibration.

## Alternatives considered

Overlapping windows, zero padding, or treating placebo power as primary. Each
would make the effective sample size or null distribution less transparent.

## Affected requirements and implementation status

FR-8, FR-10 and FR-11. Existing spike behaviour is evidence only; production
use awaits the gate in ADR-000.
