# ADR-000: Manual power-methodology approval gate

- **Status:** Proposed — **PENDING explicit product-owner approval**
- **Date:** 2026-08-14
- **Scope:** Prospective power analysis and test sizing

## Decision proposal

The production power core must remain gated until the product owner explicitly
approves the methodology decision pack. A green CI run, a merged documentation
PR, or an agent's interpretation of the evidence is not approval.

The gate may move from `PENDING` to `APPROVED` only when the product owner
records all of the following in this file or in a linked, immutable decision
record:

1. the approved methodology version and ADR identifiers;
2. the accepted limitations and any conditions of use;
3. the product-owner identity and UTC approval timestamp; and
4. the evidence commit reviewed.

Until then, `geotestlab/power/` remains an experimental methodology spike and
no production power API, UI, or recommendation may be implemented or exposed.

## Current approval record

```yaml
approval_status: pending
methodology_version: 0.5.0
evidence_commit: d7c82065907cc3bade648d534451d9f7c1f8c69d
approved_adr_ids: []
product_owner: null
approved_at_utc: null
conditions: []
```

This blank record is intentional. The coding agent must not complete it or
infer approval from a review, merge, or passing check.

## Consequences

- PR3 can document recommendations and unresolved limitations.
- PR4 cannot begin until the product owner changes the approval record.
- A later implementation PR must verify this record and preserve the approved
  methodology version in its production result contract.

## Affected requirements

FR-10, FR-11, FR-15 and FR-16; the gate also protects the separation between
statistical detectability, delivery feasibility and effect plausibility.
