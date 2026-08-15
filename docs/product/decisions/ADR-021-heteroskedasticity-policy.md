# ADR-021: Heteroskedasticity policy

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Heteroskedasticity must be evaluated on AR(1) innovations and must retain
candidate-level diagnostics, not only a single split-half ratio. A supported
production result requires an approved treatment for non-constant variance;
otherwise the result is blocked or explicitly labelled unsupported.

The current policy combines a split-variance candidate with a deterministic
contiguous-block scale-association permutation diagnostic. It is an evidence
iteration, not a claim that heteroskedasticity has been solved.

## Current evidence and limitation

False-supported cells remain concentrated in the heteroskedastic scenario:
**18/540 = 3.3%** overall false-supported rate, with heteroskedasticity
identified as the remaining limitation. The diagnostic must be tested on
independent seeds and should not be tuned to the observed suite.

## Affected requirements and implementation status

FR-7, FR-10 and FR-11. Heteroskedasticity remains an explicit production
limitation: affected cases are blocked or marked unsupported until a separately
approved treatment is available.
