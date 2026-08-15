# ADR-023: Recommendation optimisation objective

**Status:** Pending product-owner decision

## Context

GeoTestLab must compare complete design candidates without hiding match
quality, counterfactual validation, power, media delivery, effect plausibility,
region constraints, duration or cost inside a composite score. The product
still needs an explicit rule for selecting among candidates that pass those
gates.

## Proposed decision

Support two explicit objectives:

- `smallest_qualifying_design`, ordered by an analyst-supplied size metric,
  then duration and cost;
- `least_cost_qualifying_design`, ordered by cost, then size metric and
  duration.

The selected objective must be recorded in the result and export. A full
recommendation requires all gates to pass. An evidence-backed candidate with a
conditional effect bridge may be selected only as a clearly labelled
conditional recommendation. An analyst override requires a reason and keeps
all original gate statuses and limiting factors visible.

This record is intentionally pending. The implementation provides the typed
contract and UI workflow but does not represent product-owner approval of the
default objective.

## Alternatives considered

- Maximise power: rejected because a larger design can be unnecessarily costly
  after the required power gate is met.
- Minimise cost by default: rejected because the product owner may prefer the
  smallest qualifying market under a different operational objective.
- Optimise a combined score: rejected because it would collapse distinct
  methodological and delivery constraints into an opaque ranking.

## Affected requirements

- FR-15 integrated design recommendation;
- FR-22 reproducible experiment export;
- Milestone 7 effect plausibility and spend recommendation.

## Implementation status

`geotestlab.recommendation` compares explicit candidates, retains separate
gate assessments, explains limiting factors, supports conditional results and
requires/exports override rationale. Unified result export is implemented;
complete upstream candidate integration and approved-design freeze remain
follow-on work. This ADR remains pending because it does not approve a global
default objective.
