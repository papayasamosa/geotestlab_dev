# Media delivery and effect plausibility

## Delivery

The platform-profile schema describes common and platform-specific fields,
including provenance: supplied forecast, calculated, historical observed or
analyst assumption. The current registered profile is Meta auction social.

Delivery feasibility can calculate total budget from a weekly pattern,
impressions from budget and CPM, reach from impressions and frequency, and
reach percentage from reach and eligible audience. Threshold checks remain
separate. Missing values produce incomplete output; invalid values are blocked.

Delivery never derives an incremental KPI effect from spend, CPM, reach or
frequency. Ordinary media in an analytically excluded region is recorded as a
scope decision rather than silently treated as contamination.

## Effect plausibility

The effect contract records an evidence type, quality, source, source date,
adjustment state, notes and ordered low/central/high uplift scenarios. It
compares each scenario with MDE under the selected direction.

No bridge produces `unknown`. Analyst assumptions and unknown-quality evidence
produce `conditional`; adjusted evidence without explicit central approval is
blocked. Incremental CPA/CPS may be a bridge assumption but is not itself an
observed incremental KPI effect.

These outputs are inputs to recommendation gates, not a replacement for the
experiment result.
