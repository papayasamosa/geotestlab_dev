# ADR-000: Manual power-methodology approval gate

- **Status:** Approved — product-owner approval recorded below
- **Date:** 2026-08-14
- **Scope:** Prospective power analysis and test sizing

## Decision proposal

The production power core had to remain gated until the product owner
explicitly approved the methodology decision pack. A green CI run, a merged
documentation PR, or an agent's interpretation of the evidence is not
approval.

The gate may move from `PENDING` to `APPROVED` only when the product owner
records all of the following in this file or in a linked, immutable decision
record:

1. the approved methodology version and ADR identifiers;
2. the accepted limitations and any conditions of use;
3. the product-owner identity and UTC approval timestamp; and
4. the evidence commit reviewed.

The approval record below supersedes that pre-approval state. The evidence
harness remains separate from production, while the production power API and
UI may use the approved contract only when they preserve the recorded
limitations, support/blocker statuses and explicit method choices.

## Current approval record

```yaml
approval_status: approved
methodology_version: 0.5.0
evidence_suite_version: 2.1.0
evidence_commit: 6380c46d124535baa6702341d0ce02f6d2fe5478
approved_adr_ids:
  - ADR-001
  - ADR-002
  - ADR-003
  - ADR-004
  - ADR-005
  - ADR-011
  - ADR-012
  - ADR-013
  - ADR-014
  - ADR-015
  - ADR-016
  - ADR-017
  - ADR-018
  - ADR-019
  - ADR-020
  - ADR-021
  - ADR-022
product_owner: repository owner (explicit approval in Codex session)
approved_at_utc: 2026-08-14T20:11:31Z
conditions:
  - Preserve the v2.1 limitations and support/blocker status in production results.
  - Keep simulation method and fit method explicit; do not add an implicit best-method default.
  - This approval covers statistical detectability only, not media feasibility or effect plausibility.
```

This record was completed after explicit product-owner approval in the Codex
session at the timestamp above. The approval does not erase the limitations
documented by the evidence or authorize media-feasibility/effect-plausibility
features.

## Consequences

- PR3 can document recommendations and unresolved limitations.
- Production power implementation may proceed under the conditions in the
  approval record. Later changes that alter numerical semantics require a new
  evidence and decision review.
- The production result contract must preserve the approved methodology
  version and must not be confused with the separate evidence harness.

## Affected requirements

FR-10, FR-11, FR-15 and FR-16; the gate also protects the separation between
statistical detectability, delivery feasibility and effect plausibility.
