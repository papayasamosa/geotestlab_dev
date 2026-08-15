# ADR-013: Acceptance criteria and scenario weighting

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

The proposed acceptance thresholds are decision criteria, not tunable targets:

| Metric | Proposed threshold | v2.1 result |
|---|---:|---:|
| Mean absolute power bias | 0.05 | 0.102 |
| Worst supported absolute power bias | 0.15 | 0.477 |
| False-supported rate | 0.00 | 0.033 |
| Seed-sensitivity power standard deviation | 0.05 | 0.084 |

The product owner approved methodology version 0.5.0 with these calibration
failures retained as explicit limitations and support/blocker conditions in
ADR-000. Future evidence work must still decide whether any revised acceptance
policy is flat across scenarios or scenario-weighted before changing the
production semantics.

## Alternatives considered

Flat thresholds, scenario-weighted thresholds, and a hard protected-scenario
floor plus aggregate metrics. The third option is a candidate for review, not
an approved policy.

## Affected requirements and implementation status

FR-10 and FR-11. The current production contract preserves the observed
limitations and does not reinterpret the proposed thresholds as a hidden
qualification score.
