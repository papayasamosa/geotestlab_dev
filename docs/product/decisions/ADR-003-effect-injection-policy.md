# ADR-003: Relative and absolute effect injection

- **Status:** Approved — product-owner approval recorded in ADR-000
- **Date:** 2026-08-14

## Decision proposal

Effect injection must be explicit in every analysis: `relative` for KPI-scale
uplift and `absolute` for low-volume or otherwise additive KPI changes. The
result must carry the injection mode and units. A relative effect must not be
inferred from a field named `Population` or from the number of regions.

The first production candidate may support both modes, but the product must
validate that the selected mode is meaningful for the KPI and scenario.

## Rationale and limitations

The evidence suite uses relative injection for ordinary market scenarios and
absolute injection for the low-volume scenario. That is coverage of two
semantics, not approval of the default for all KPIs. KPI scale, zero values,
and aggregation must be reviewed with the source-data contract.

## Alternatives considered

Relative-only, absolute-only, and a user-entered conversion layer. Relative
and absolute modes with explicit units preserve the most information while
avoiding an unsafe implicit conversion.

## Affected requirements and implementation status

FR-10, FR-11 and TS-FR1. The canonical regional KPI contract is the required
input. The production result records the explicit injection mode and units;
it does not infer a relative effect from population or region count.
