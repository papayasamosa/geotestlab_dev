# Data flow

```text
source workbooks
    -> canonical RegionalKPIDataset / market data
    -> matching snapshot (test, controls, constraints)
    -> validation result and counterfactual diagnostics
    -> production power result
    -> media delivery assessment
    -> effect plausibility assessment
    -> candidate gate comparison and recommendation
    -> experiment record + unified JSON export
```

Power consumes the canonical KPI dataset and explicit regional design. Media
delivery consumes a platform-bound media plan, thresholds and experiment scope.
Effect plausibility consumes explicit evidence and MDE, with delivery identity
recorded separately. Recommendation consumes candidate-level statuses; it does
not recompute or collapse the upstream methods.

The export contains stage status/fingerprints plus result summaries. This makes
it possible to review a result while seeing whether its inputs are current.
