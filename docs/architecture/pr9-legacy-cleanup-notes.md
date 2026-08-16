# PR9 legacy cleanup — what moved and what deliberately didn't

PR9 ("Legacy UI deletion and bootstrap cleanup") was the final PR of the
UI/UX overhaul programme (PR1–PR9). This note records what it did and,
just as importantly, what it deliberately left in place and why — following
the same honest-scope-reduction pattern used throughout PR2–PR8 (e.g. PR4's
decision not to internally restructure `render_time_series_validation`).

## What PR9 removed or moved

- Deleted `inspect_excel_sheet()` — a defined-but-never-called dead function.
- Deleted unused `geotestlab/ui` scaffolding that had been built ahead of
  need in PR2 but never wired into the app: the `EvaluateStep` enum family
  (`EVALUATE_STEP_ORDER`/`EVALUATE_STEP_TITLES`/`advance_evaluate()`/
  `retreat_evaluate()` — the Evaluate journey has no internal step
  navigation of its own, unlike the four-step Plan journey), and the
  `render_page_header`/`render_next_action`/`render_technical_details`/
  `format_percent`/`format_date_range` helpers, none of which had any call
  site in `geotestmatch.py` or any `geotestlab/*/ui.py` module.
- Cleaned up naming fossils from the pre-PR2 eight-tab era that survived
  the PR2 conversion as comments/widget keys with no functional effect
  (a stale `tab8` comment, a `run_bayes_tab4` widget key).
- Extracted the data-quality report renderer and pre-run validation scan
  into `geotestlab/ui/data_quality.py` (`quality_blocking_errors`,
  `render_kpi_quality_report`, `validate_data`).
- Extracted MCMC diagnostics rendering into `geotestlab/bayesian/ui.py`
  (`render_mcmc_diagnostics`), matching the existing `power/ui.py`-style
  pattern used by the media/effect/recommendation packages.

Net effect: `geotestmatch.py` shrank from ~7,460 to ~7,090 lines. Modest,
but every line removed was either genuinely dead or moved to a home with a
real test boundary.

## What PR9 deliberately left in `geotestmatch.py`

Two functions still account for the large majority of the file:

- `render_structural_matching_tab` (~1,460 lines) — the former Tab 1 body.
- `render_time_series_validation` + `render_method_comparison_table`
  (~2,400 lines combined) — the former Tab 2/Tab 3 bodies, still branching
  internally on `mode == "Design"` vs. `mode == "Evaluate"` rather than
  being two separate functions.

Both were confirmed, via a full closure/dependency scan before PR9 started,
to read a small set of module-level runtime variables computed by the
~217-line workbook/market-load block earlier in `geotestmatch.py`:
`active_features`, `agg_df`, `geo_col`, `geography_level`, `market`,
`market_df_raw`, `match_mode`, `strategy_labels`, `total_market_pop` — plus,
between them, upward of 30–38 distinct `st.session_state` keys.

Extracting either function safely requires first turning that workbook-load
block into a function that returns a small typed context object (or
threading all nine names through explicit parameters at both call sites),
so the moved code doesn't silently break on a missing module-level name.
That is a real, scoped, low-ambiguity refactor — but it is also the single
highest-risk change available in this programme: it touches the two
functions that contain the bulk of the app's live matching-execution and
time-series-validation UI logic, exactly the surface the numerical
characterisation golden-test suite exists to protect. Bundling it into the
same PR as the rest of PR9's lower-risk cleanup would have traded a
well-understood, easily-reviewed diff for a much larger one under time
pressure, for a payoff (a smaller `geotestmatch.py`) that doesn't change
behaviour for any user.

**Recommendation for a future PR9b**, should the team want to pursue it:

1. Extract the workbook/market-load block into a function returning a
   `MatchingContext`-style dataclass (or equivalent), used at both the
   `render_structural_matching_tab` and `render_time_series_validation`
   call sites.
2. Move `render_structural_matching_tab` to
   `geotestlab/ui/region_matching.py` (or similar) in its own PR, verified
   against the full numerical-characterisation suite.
3. Split `render_time_series_validation`'s `mode`-branching into
   `_render_design_validation`/`_render_evaluate_validation` as part of (or
   before) moving it to `geotestlab/validation/ui.py`, in a separate PR from
   step 2 so each diff stays independently reviewable.

Until that follow-up work happens, `geotestmatch.py` is not "primarily
bootstrap/orchestration" in the strict sense the original programme plan's
PR9 exit criteria described — it is a Streamlit entry point that still
contains substantial UI-rendering logic for two of its four Plan-journey
steps. This is stated plainly here rather than claimed as complete.
