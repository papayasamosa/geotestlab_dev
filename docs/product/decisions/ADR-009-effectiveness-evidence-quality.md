# ADR-009: Effectiveness-evidence quality and scenarios

**Status:** Pending product-owner decision

## Context

Statistical detectability, media delivery and expected KPI response answer
different questions. Effectiveness evidence can inform an uplift assumption,
but an observed incremental CPA/CPS or an adjusted historical estimate is not
itself a guaranteed KPI effect.

## Proposed decision

Permit explicit evidence bridges from prior same-market/platform geo tests,
comparable-market tests, MMM, incremental CPA/CPS, platform lift forecasts and
analyst assumptions. Every bridge must record its source, source date, quality,
notes and ordered low/central/high relative-uplift scenarios. Adjusted or
outlier-excluded evidence must not become the central scenario silently; it
requires explicit approval and remains visible as adjusted.

Where no bridge is supplied, effect plausibility is `unknown`. A bridge may be
compared with MDE, but the comparison does not itself produce an integrated
design recommendation or combine delivery, power and plausibility into one
score.

This record is intentionally still pending. The implementation is a typed
workflow contract and does not represent approval of an evidence hierarchy.

## Alternatives considered

- Infer uplift from budget, CPM, reach or frequency: rejected because delivery
  is not incremental KPI response.
- Use one central estimate without scenarios: rejected because uncertainty and
  adjusted estimates would be hidden.
- Allow adjusted historical estimates to become central automatically: rejected
  because the transformation would be unauditable.

## Affected requirements

- FR-14 effect plausibility and spend sufficiency;
- FR-15 integrated design recommendation;
- FR-22 reproducible experiment export;
- Milestone 7 effect plausibility and spend recommendation.

## Implementation status

`geotestlab.effect` contains the evidence/scenario contract, provenance, MDE
comparison, staleness fingerprint and dedicated UI. The typed recommendation
consumer is implemented, but the evidence-quality policy remains pending and
the normal recommendation path is not yet fully upstream-integrated.
