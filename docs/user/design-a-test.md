# Design and size a test

This guide covers the prospective workflow. Run the stages in order when the
design is sufficiently specified, but a detectability-only power run can be
useful before media forecasts are available.

## 1. Build the regional design

In **Region Matching**, select the market and geography level, choose the test
regions, and run the selected matching strategy. Review structural distance,
standardised mean differences, population share and the control pool. Region
constraints and exclusions must be explicit.

The executed test/control groups are frozen in the session snapshot. Changing
widgets does not silently rewrite the last completed result; run matching again
when the design changes.

## 2. Validate the counterfactual

Upload or select the canonical KPI dataset in **Validate Test Design**. Select
the historical and planned test periods and frequency. The validation tab
continues to validate source-backed periods; prospective power separately
retains a source-backed historical holdout and optional future campaign dates.
The current workflow assigns Elastic
Net to structurally matched or user-selected controls and LASSO to
data-optimised controls; it does not expose a validation fit-method selector.
Review rolling-origin error, bias, overfitting, autocorrelation, placebo
diagnostics and the Counterfactual Confidence rating.

A completed validation stage means a result exists. It does not automatically
mean the design is recommendation-quality. The recommendation table therefore
keeps match quality and counterfactual status as explicit inputs.

## 3. Run production power

In **Power & Test Sizing**, enter or confirm:

- metric and historical calibration period;
- source-backed analytical holdout, planned duration and optional future
  campaign dates;
- simulation method and counterfactual fit;
- positive, negative or two-sided effect direction;
- target effect, target power and simulation count;
- MDE bounds and minimum-history policy.

The output reports power curves, target-power estimates, MDE, confidence
intervals, support status, warnings and blockers. The analytical holdout must
be contiguous source history immediately after calibration; optional future
campaign dates are metadata and are never used as observations. A result that
is incomplete, stale or unsupported is not usable for a full recommendation.

## 4. Assess media delivery

In **Media Delivery Feasibility**, choose a platform profile and enter supplied
or forecast values. The result labels calculated fields and preserves input
provenance. Reach and frequency calculations answer delivery questions only;
they do not infer incremental KPI impact.

Record excluded experiment regions separately from ordinary media activity and
review control-region activity and spillover assumptions. Delivery thresholds
are optional in the current contract: when supplied they are checked, while
missing thresholds mean that no threshold check has been performed. Missing
required forecast inputs produce incomplete output rather than an optimistic
pass.

## 5. Record effect plausibility

In **Effect Plausibility**, record the source, quality, date and ordered low,
central and high uplift scenarios. Adjusted evidence needs explicit central
approval. Analyst assumptions and unknown-quality evidence remain conditional.

No evidence bridge means effect plausibility is unknown. Power and delivery
remain reportable, but the product must not call spend sufficient for a KPI
effect.

## 6. Compare designs

In **Integrated Design Recommendation**, the current UI accepts one complete
candidate per row. Keep these columns separate:

- match quality;
- counterfactual validation;
- power support, usability and target-power result;
- media delivery;
- effect status and MDE comparison;
- region constraints;
- size metric, duration and cost.

Choose `smallest_qualifying_design` or `least_cost_qualifying_design`. The
selection is not a composite score. A conditional effect bridge produces a
conditional recommendation, not a full recommendation. If no candidate passes,
the output names the limiting factors.

An override requires a reason. The reason and the original gate statuses are
included in the result and export. When upstream stages have run, the current
UI prefills a selected-design row from their current, non-stale validation,
power, delivery and effect results. That row remains editable, uses a
placeholder size metric, does not yet represent a full scenario grid, and does
not automatically carry every upstream design constraint. Treat changed or
additional rows as analyst-supplied assumptions until the complete typed
candidate integration is delivered.
