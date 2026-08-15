# ADR-015: Production simulation count and reproducibility

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Production simulation count, random seed, and separate calibration/detection
streams must be explicit in the analysis record. The CI evidence setting of
**500 simulations** is a tractable characterization setting and must not be
copied into production without a precision and runtime decision.

The product owner must approve a count using a power-uncertainty target, a
runtime budget, and reproducibility requirements. Increasing the count cannot
repair a biased method or replace scenario coverage.

## Current evidence

The v2.1 suite uses 500 simulations per run, 5 data seeds and 3 simulation
seeds. Its runtime p95 is **0.729 seconds** per run, but the study still shows
seed sensitivity **0.084**, above the proposed **0.05** threshold.

## Affected requirements and implementation status

FR-10, FR-11 and FR-22. No universal production simulation count is approved;
the production caller must provide and export an explicit count and seed.
