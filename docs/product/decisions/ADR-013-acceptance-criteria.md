# ADR-013: Acceptance criteria and scenario weighting

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

The proposed acceptance thresholds are decision criteria, not tunable targets:

| Metric | Proposed threshold | v2.1 result |
|---|---:|---:|
| Mean absolute power bias | 0.05 | 0.102 |
| Worst supported absolute power bias | 0.15 | 0.477 |
| False-supported rate | 0.00 | 0.033 |
| Seed-sensitivity power standard deviation | 0.05 | 0.084 |

Do not approve the methodology while these failures remain unexplained. The
product owner must decide whether final acceptance is flat across scenarios or
scenario-weighted, with the weighting and protected scenarios recorded before
production implementation.

## Alternatives considered

Flat thresholds, scenario-weighted thresholds, and a hard protected-scenario
floor plus aggregate metrics. The third option is a candidate for review, not
an approved policy.

## Affected requirements and implementation status

FR-10 and FR-11. This ADR resolves neither the thresholds nor the approval;
it makes the open decision explicit.
