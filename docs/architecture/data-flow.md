# Data flow

```text
source workbooks
    -> canonical RegionalKPIDataset / market data
    -> matching snapshot (test, controls, constraints)
    -> validation result and counterfactual diagnostics
    -> selected-design production power result
    -> (target) candidate scenario builder with matched controls and validation
    -> media delivery assessment
    -> effect plausibility assessment
    -> candidate gate comparison and recommendation
    -> experiment record + unified JSON export
```

Power consumes the canonical KPI dataset and explicit regional design. The
current scenario engine can construct share/duration candidates, but does not
yet guarantee the complete matched-control and historical-validation pipeline
shown in the target flow. Media delivery consumes a platform-bound media plan,
thresholds and experiment scope. Effect plausibility consumes explicit evidence
and MDE, with delivery identity recorded separately. Recommendation consumes
candidate-level statuses; the current UI still permits manually supplied
candidate rows, while the target flow will consume typed upstream results and
will not recompute or collapse the upstream methods.

The export contains stage status/fingerprints plus result summaries, including
Bayesian observed-impact fields when that stage has produced them. This makes
it possible to review a result while seeing whether its inputs are current.
