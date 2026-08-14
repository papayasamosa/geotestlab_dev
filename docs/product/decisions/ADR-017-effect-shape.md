# ADR-017: Effect shape

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

The first production candidate should require an explicit effect shape and
should start with a step effect only where the campaign brief supports an
immediate, sustained intervention. Ramp, delayed-start, decay and carryover
shapes require separate calibration evidence and must not be silently mapped
to a step.

## Current evidence and limitation

The v2.1 evidence harness uses `effect_shape: step`. It therefore says nothing
about the calibration of ramp or carryover effects. Shape-specific power must
be reported separately rather than averaged into the step result.

## Affected requirements and implementation status

FR-10, FR-11 and TS-FR1. No shape default is approved.
