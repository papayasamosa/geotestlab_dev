# ADR-008: First platform-profile scope

**Status:** Pending product-owner decision

## Context

The prospective workflow needs platform-aware delivery inputs, but platform
selection must remain separate from statistical power. A profile must describe
fields, units and provenance without turning a delivery forecast into a claim
about incremental KPI impact.

## Proposed decision

Use a generic declarative platform-profile contract with a registry of profile
identifiers. The first implemented profile is `meta_auction_social`, covering
common budget, delivery, audience, campaign, geographic-targeting, control-
activity, spillover and forecast-metadata fields. Each value carries one of
four explicit provenance labels: supplied forecast, calculated, historical
observed or analyst assumption. Custom fields remain available for profile
extensions.

This record is intentionally still pending. Implementing the schema and
testing the profile does not constitute product-owner approval of the first
release profile set.

## Alternatives considered

- Put Meta-specific fields directly in the Streamlit app: rejected because it
  would make later profiles and export compatibility harder.
- Treat every input as an analyst assumption: rejected because it hides the
  difference between supplied forecasts, observations and calculations.
- Make platform selection part of the power engine: rejected because delivery
  feasibility and statistical detectability are separate decision layers.

## Affected requirements

- FR-12 platform and channel selection;
- FR-13 media-delivery feasibility;
- FR-22 reproducible experiment export;
- Milestone 6 platform-aware media feasibility.

## Implementation status

The generic schema, provenance model, Meta profile registration and validation
tests are implemented in `geotestlab.media`. Delivery calculations and UI are
deferred to the follow-up media-feasibility change.
