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

## The workflow

The app opens on an entry screen with three choices: **Plan a new geo test**,
**Analyse a completed geo test**, or **Open a saved experiment** (loads a
previously exported JSON record directly from the entry screen).

**Plan a new geo test** is a guided, four-step journey:

1. **Choose regions** — select test regions and construct controls using
   structural or KPI-pattern matching.
2. **Check design** — historical counterfactual quality (the selected
   validation method, rolling-origin diagnostics) and statistical power (the
   production power contract, candidate shares/durations, MDE and support
   status) are assessed together on one step; each result stays separate —
   neither overrides the other.
3. **Media and expected impact** — media delivery (budget, CPM, impressions,
   reach, frequency and thresholds using the registered Meta platform
   profile, with a weekly-spend preset/custom editor) and effect
   plausibility (a dated evidence bridge and low/central/high KPI-uplift
   scenarios compared with the MDE inherited from Check design, or an
   explicit "I do not have effectiveness evidence" choice) are assessed
   together; each result stays separate. The evidence-quality policy
   remains pending.
4. **Review and approve** — compare typed upstream candidates under an
   explicit smallest-design or least-cost objective, then freeze the design.

Back/Next buttons or the step selector move between steps without losing
state.

**Analyse a completed geo test** covers **Results** — evaluate a completed
test and estimate observed impact — with an optional **Run advanced
uncertainty analysis** action that runs the Bayesian time-based regression
workflow when its sampling inputs and diagnostics are appropriate.

A compact workflow-status summary (shown once past the entry screen) tracks
current, stale and needs-attention states plus the next recommended action.

The experiment-record expander is the audit trail. It shows stage statuses,
fingerprints, stale results, frozen design versions, reproducibility metadata,
stakeholder/technical summaries and the unified JSON export.

After a current recommendation is available, enter an analyst label or notes if
needed and choose **Freeze approved design**. The frozen snapshot is built from
executed matching and analytical results, records the source-data fingerprint,
power and recommendation evidence, and keeps optional media/effect stages
explicitly marked when they were not supplied. A later approval creates a new
version; it does not overwrite earlier versions.

When evaluating a completed test, **Measure Test Impact** can load the active
frozen version's test/control regions and planned periods as defaults. Review
the source fingerprint and any live-input differences before running the
evaluation.

To reopen a local JSON export, use **Open local experiment record** in the
experiment-record expander. The loader restores metadata and frozen versions,
then explicitly asks for any missing source workbooks; it never embeds or
pretends to restore sensitive KPI observations.

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
