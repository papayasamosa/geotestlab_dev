# Architecture overview

`geotestmatch.py` is the Streamlit entry point and UI adapter. Analytical and
workflow contracts live in Streamlit-free packages:

- `geotestlab/data` — canonical ingestion, quality and mapping;
- `geotestlab/matching` — structural/KPI-pattern matching and constraints;
- `geotestlab/validation` — counterfactual validation and diagnostics;
- `geotestlab/bayesian` — Bayesian TBR core and diagnostics;
- `geotestlab/power` — methodology harness and production power contract;
- `geotestlab/media` — platform profiles and delivery feasibility;
- `geotestlab/effect` — evidence and MDE comparisons;
- `geotestlab/recommendation` — explicit candidate gates and objective;
- `geotestlab/experiment` — identity, fingerprints, stage status, freeze
  foundations and unified export summaries.

The UI coordinates these packages through session state. Typed result objects
are exported through the experiment record; raw source data is not embedded in
the result summaries.
