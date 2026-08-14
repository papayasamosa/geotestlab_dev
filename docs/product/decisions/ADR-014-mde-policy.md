# ADR-014: MDE bounds and tolerance

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

MDE search must use explicit, KPI-unit-aware bounds and a recorded tolerance;
the result must distinguish “MDE reached” from “MDE not reached within the
requested bounds.” The current spike uses scenario-specific bounds and a
tolerance of **0.5** in the scenario's injection units. Those are evidence
harness settings, not approved product defaults.

The approved production bounds must be wide enough to contain the business
question and must not be widened automatically after a failed search.

## Current evidence

The v2.1 false-MDE rate is **0/522 = 0%** among eligible completed runs, while
mean relative MDE bias is **0.229** against a proposed threshold of **0.25**.
This does not establish adequacy for untested KPI scales or effect shapes.

## Affected requirements and implementation status

FR-10, FR-11 and TS-FR1. The production contract must receive these settings
explicitly until product-level defaults are separately specified.
