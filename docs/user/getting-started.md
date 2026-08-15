# Getting started

GeoTestLab is a Streamlit application for designing, validating, sizing and
evaluating geographic experiments. It is intended for analysts who can review
the assumptions behind a geo-test; it is not a black-box campaign optimiser.

## Install and launch

Use Python 3.11. Follow the platform-specific setup in the root
[README.md](../../README.md). On managed Windows machines, put virtualenvs and
package caches on `D:` as shown there.

Launch from the repository root:

```bash
streamlit run geotestmatch.py
```

The default workbook is loaded from `data/`. Before relying on a result, check
the market, geography level, metric, date frequency and data-quality report.

## The workflow tabs

1. **Region Matching** — choose test regions and construct controls using
   structural or KPI-pattern matching.
2. **Validate Test Design** — assess historical counterfactual quality with the
   selected validation method and rolling-origin diagnostics.
3. **Power & Test Sizing** — run the explicit production power contract and
   compare typed candidate shares, durations, MDE and support status.
4. **Media Delivery Feasibility** — assess budget, CPM, impressions, reach,
   frequency and thresholds using the registered Meta platform profile.
5. **Effect Plausibility** — record a dated evidence bridge and low/central/high
   KPI-uplift scenarios, then compare them with MDE. The evidence-quality policy
   remains pending.
6. **Design Recommendation / Approve Design** — compare typed upstream
   candidates under an explicit smallest-design or least-cost objective.
7. **Measure Test Impact** — evaluate a completed test and estimate observed
   impact.
8. **Bayesian TBR** — run the Bayesian time-based regression workflow when its
   sampling inputs and diagnostics are appropriate.

The app follows this lifecycle directly. Region Matching through Design
Recommendation / Approve Design form the **Plan a Test** phase. Measure Test
Impact and Bayesian TBR form **Evaluate a Completed Test**. A visible workflow
status summary shows current, stale and needs-attention states plus the next
recommended action.

The experiment-record expander is the audit trail. It shows stage statuses,
fingerprints, stale results, frozen design versions and the unified JSON export.

## First-run checklist

- Confirm the uploaded data contains the required region, metric and date
  fields.
- Complete and run matching; retain the executed test/control snapshot.
- Validate historical fit before interpreting power.
- Record the target power, effect direction, duration and simulation method.
- Treat media forecasts as delivery evidence, not KPI incrementality.
- Add effectiveness evidence before asking whether spend sufficiency is
  plausible.
- Review every recommendation gate and limiting factor before downloading the
  experiment record.
