# ADR-011: Counterfactual fit policy

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

The fit method must be an explicit, versioned configuration. The production
contract must not silently default between OLS, Elastic Net and LASSO, and
must return the selected method and diagnostics. A method that fails safety or
minimum-history checks blocks the result rather than being hidden by a
different fit.

## Current evidence

The v2.1 suite evaluates OLS, Elastic Net and LASSO across the two candidate
simulation methods. It shows scenario-dependent behaviour rather than a
single universally dominant fit. The aggregate study still fails the proposed
power-bias and seed-sensitivity thresholds, so no fit is approved as the
production default.

## Alternatives considered

OLS-only, regularised-only, automatic best-fit selection, or explicit
multi-fit comparison. Explicit configuration with evidence-led selection is
the recommended control; automatic best-fit selection would make the method
and uncertainty difficult to reproduce.

## Affected requirements and implementation status

FR-6, FR-7, FR-10 and FR-11. This ADR defines the selection rule, not a
production fit implementation.
