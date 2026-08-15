# ADR-012: One-sided and two-sided effect direction

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

The analysis must require an explicit effect direction: positive one-sided,
negative one-sided, or two-sided. The v2.1 evidence is positive one-sided and
must not be presented as evidence for negative or two-sided operating
characteristics. The selected tail must be stored in the result and export.

## Rationale and limitations

One-sided positive testing is appropriate only when the business decision and
pre-test hypothesis make the direction defensible. Two-sided analysis should
be the conservative choice when either direction would change the decision.
Separate calibration evidence is required for each supported tail.

## Affected requirements and implementation status

FR-10, FR-11 and TS-FR1. The production contract requires the direction
explicitly and stores it in the result and export; no implicit direction
default is approved.
