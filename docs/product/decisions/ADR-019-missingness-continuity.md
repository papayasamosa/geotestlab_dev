# ADR-019: Missingness and time continuity

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

Missing KPI observations must remain missing through preparation and modelling;
they must never be converted to zero. Duplicate analytical keys, blank region
classifications, non-numeric KPI cells, missing dates and frequency gaps must
be diagnosed before power estimation. A result must report requested periods,
retained periods and effective test periods.

The current evidence suite treats partial test-region missingness as a safety
scenario and duplicate keys as an expected block. Frequency continuity rules
must be applied using dates, not row counts alone.

## Affected requirements and implementation status

FR-2, FR-6, FR-10 and TS-FR1. The canonical regional KPI contract is the source
for future production power input.
