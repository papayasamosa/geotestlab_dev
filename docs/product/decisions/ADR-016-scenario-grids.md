# ADR-016: Candidate market-share and duration grids

- **Status:** Proposed — pending product-owner approval
- **Date:** 2026-08-14

## Decision proposal

Scenario sizing must evaluate explicit candidate market-share and duration
grids, retain requested and achieved values, and show the regions and dates in
each candidate. The default grid is proposed as:

- market share: **10%, 20%, 30%, 40%, 50%**;
- duration: **2, 4, 6, 8 and 12 weeks**.

These are product-specification candidates, not approved defaults. Actual
market share must use the selected market-size measure (population, customers,
historical KPI volume, revenue, addressable audience or custom weight), never
the number of regions. Indivisible regions and unavailable dates must remain
visible as limitations.

## Alternatives considered

Region-count percentages, a single business-supplied scenario, and an
automatically optimised grid. Region counts are explicitly rejected for sizing;
automatic optimisation must wait for an approved objective and constraints.

## Affected requirements and implementation status

TS-FR1–TS-FR3 and FR-10–FR-15. The scenario engine is a later PR and is gated
by ADR-000.
