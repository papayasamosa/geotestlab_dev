# ADR-002: Detection criterion

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Use `interval_excludes_zero` as the candidate common detection criterion. It is
the criterion currently exercised across the model and residual simulation
paths. `empirical_placebo_threshold` remains method-specific to
`placebo_empirical`; `sign_and_threshold` remains unimplemented and must not
be implied by the UI.

The production contract must report the criterion and tail explicitly. It must
not silently switch criteria when a method or fit fails.

## Rationale and limitations

The v2.1 null calibration mean is **0.0071** across 522 completed runs, below
the proposed absolute error threshold of 0.02, but the overall power and
seed-sensitivity thresholds still fail. Null calibration alone is therefore
not evidence that the criterion is approved.

## Alternatives considered

Empirical placebo thresholds, a sign-and-threshold rule, and posterior
probability thresholds. The latter two require additional decision fields and
validation evidence.

## Affected requirements and implementation status

FR-10, FR-11 and the detection output contract. This remains configuration and
evidence only; no production API is selected.
