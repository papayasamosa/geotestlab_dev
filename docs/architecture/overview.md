# Architecture overview

`geotestmatch.py` is the Streamlit entry point and orchestrator: it drives
the task-led navigation shell (entry screen, the four-step "Plan a new geo
test" journey, and "Analyse a completed geo test"), owns the module-level
session-state bootstrap, and still contains the two largest legacy
rendering bodies (structural matching and time-series validation/Bayesian
TBR) that predate the UI/UX overhaul programme — see
`docs/architecture/pr9-legacy-cleanup-notes.md` for what remains a known,
deliberately-deferred extraction. Analytical and workflow contracts live in
Streamlit-free packages:

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

`geotestlab/ui` is the UI-adapter support package (it does import
Streamlit, unlike the packages above): navigation state
(`geotestlab/ui/navigation.py`, `geotestlab/ui/state.py`), the
label-translation registry (`geotestlab/ui/labels.py`) that keeps internal
enum/status vocabulary out of analyst-facing text, the shared status-line
component (`geotestlab/ui/components/status.py`), and the extracted
data-quality report renderer (`geotestlab/ui/data_quality.py`). Several
domain packages similarly carry their own thin `ui.py` Streamlit adapter
next to their pure logic — `geotestlab/power/ui.py`,
`geotestlab/media/ui.py`, `geotestlab/effect/ui.py`,
`geotestlab/recommendation/ui.py`, `geotestlab/bayesian/ui.py` — each
called from a short slot guard in `geotestmatch.py` rather than rendering
inline.

The UI coordinates these packages through session state. Typed result objects
are exported through the experiment record; raw source data is not embedded in
the result summaries.
