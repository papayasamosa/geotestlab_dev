# ADR-022: Power uncertainty interpretation

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Every reported power estimate must include a simulation uncertainty interval
and the simulation count. The product must distinguish conditional uncertainty
(holding the fitted counterfactual and approved parameters fixed) from
uncertainty that includes model, parameter and data-generation variation. It
must not present a single point estimate without the status and assumptions
that produced it.

The v2.1 study's seed-sensitivity metric is evidence about variation across
data/simulation seeds; it is not itself a complete confidence interval for a
future experiment.

## Current evidence

Clopper–Pearson intervals are present in the spike result contract. The study
still reports mean seed-sensitivity standard deviation **0.084**, above the
proposed **0.05** threshold, so uncertainty interpretation remains unresolved.

## Affected requirements and implementation status

FR-10, FR-11, FR-19 and FR-22. The production uncertainty semantics require
explicit approval.
