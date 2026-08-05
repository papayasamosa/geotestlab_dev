# Power-Analysis Methodology Spike — Decision Evidence

**Document type:** Methodology spike report (decision evidence)
**Stage:** 5 — `spike/power-analysis-methodology` (evidence strengthened by
`test/power-methodology-realistic-evidence`, see section 9)
**Date:** 5 August 2026 (original 4 August 2026)
**Status:** For methodology approval (does **not** authorise production implementation)

## 1. Purpose

This spike produces **decision evidence** for the prospective power-analysis and
test-sizing methodology required by
[`docs/product/power-analysis-and-test-sizing.md`](../product/power-analysis-and-test-sizing.md).
It is a **pure prototype** validated against **controlled synthetic cases** with a
known counterfactual and known AR(1) noise, where the true null distribution of the
test-window total is analytic. It is **not** the production power engine, adds no
platform/budget/delivery/effect-plausibility UI, and does **not** treat the existing
closed-form placebo power preview (`compute_power_curve`) as approved.

Prototype package: `geotestlab/power/` (pure, no Streamlit).
Controlled tests: `tests/test_power_spike.py` (131 tests).
Realistic market-shaped evidence: `geotestlab/power/market_evidence.py` +
`tests/test_market_evidence.py`; full deterministic report at
`docs/spikes/evidence/power-methodology-evidence.json` (see section 9).
Corrected by: `fix/power-spike-correctness` (see section 7);
`fix/power-spike-review-round-2` and `fix/experiment-provenance-review-round-2`
added further corrections before this evidence stage.

## 2. Controlled synthetic design

Each synthetic case has:

- controls `c_j,t = base_j + w_j·signal_t + N(0, σ_c)`;
- test counterfactual `cf_t = b0 + Σ b_j·c_j,t` — an **exact** linear combination, so
  the counterfactual model recovers it with zero model error;
- AR(1) noise in levels `e_t = ρ·e_{t-1} + N(0, σ)`;
- a known effect injected in the test window (relative `%` or absolute, step or ramp).

Because the counterfactual and noise are known, the null total
`T ~ N(Σcf_test, Var(Σe))` is analytic, and the prototype's power estimates can be
checked against the exact closed form:

$$Var(S_n) = \frac{\sigma^2}{1-\rho^2}\left(n + 2\sum_{k=1}^{n-1}(n-k)\rho^k\right)$$

## 3. Controlled validation results

| Check | Finding |
|---|---|
| Detection machinery vs analytic power | ≤ 0.03 absolute error (n_sim = 2000) — the effect-injection + detection path reproduces the exact power for the fitted null |
| Noise model (AR(1) fit) vs truth | ρ̂ and σ̂ recover truth within sampling error; null total SD within 25% of the analytic SD for ~120 pre-periods |
| Null calibration (effect = 0) | power ≈ α (0.05) — the false-positive rate is at the nominal level |
| Two-sided vs one-sided | two-sided power < one-sided power for the same positive effect; two-sided null ≈ α; one-sided-negative does not "detect" a positive effect |
| Relative vs absolute injection | both match the analytic shift (relative scales the counterfactual total; absolute is a constant per-period shift) |
| Autocorrelation | higher ρ → wider null → lower power at the same effect; the AR(1) model captures this |
| Effect shape | a ramp of peak e injects roughly half the total of a step e (power materially lower for the same peak) |
| MDE search | MDE recovers the analytic effect meeting target power within the search tolerance; explicit "not reached" when bounds are too tight |
| Power uncertainty | Clopper–Pearson CI on every power estimate; CI width shrinks as n_sim grows |

## 4. Decision evidence by methodology question

### 4.1 Primary simulation method

**Options:** historical residual simulation; effect injection into held-out
windows; model-based counterfactual simulation; bootstrap / placebo empirical.

**Evidence:** model-based counterfactual simulation (fit the test on its controls,
fit AR(1) on the residuals, simulate test-window counterfactual totals) is the only
candidate that directly aligns with the app's evaluation method (PA-FR2) and
validates tightly (≤ 0.03 vs analytic). Residual (bootstrap) simulation matches for
independent noise but ignores autocorrelation. Placebo-window empirical power is the
legacy closed-form method.

**Recommendation:** **model-based counterfactual simulation** as the primary
first-release method, with **placebo-window empirical power kept as a cross-check**
(not the primary), and **residual simulation available for independent-noise cases**.

### 4.2 Detection criterion

**Options:** interval excludes zero; empirical placebo threshold; sign + threshold;
posterior probability.

**Evidence:** "interval excludes zero" on the simulated null total distribution is
the most interpretable, calibrates to α at effect 0, and is identical in structure
to the app's validation intervals.

**Recommendation:** **interval excludes zero** (default one-sided for a stated
uplift direction, two-sided available), with the criterion recorded in every result
and export (PA-FR4).

### 4.3 Positive, negative, and two-sided effects

All three sides are implemented (`one_sided_positive`, `one_sided_negative`, `two_sided`).
The effect **magnitude is always non-negative**; the direction is controlled by `side`
(`one_sided_negative` injects a negative shift from the positive magnitude). The MDE is
always reported as a non-negative magnitude, and the one-sided MDEs are symmetric.
Two-sided power is strictly lower and the two-sided MDE larger; a one-sided-negative
test should not be used to evaluate a positive-effect hypothesis. Recommendation: expose
the side as an explicit input; default to one-sided only when the effect direction is
pre-specified.

### 4.4 Relative versus absolute effect injection

Both are implemented and validated. Relative injection (constant `%` uplift) is the
natural default for KPI readouts and matches the product spec's first-release option
(PA-FR3). Absolute injection is a constant per-period shift (useful for low-volume or
near-zero KPIs where a relative shift is ill-defined). Recommendation: **relative
first**, absolute supported, with the policy recorded in the result.

### 4.5 Effect shape

The synthetic generator supports step and ramp **for fixtures**. The spike SERVICE
implements **step only**: `ramp` is rejected until a real ramp simulation path exists
in the service — the generator's ramp must not be mistaken for service support. A ramp
of peak `e` injects ≈ half the total effect of a step `e` (generator evidence). For
first release, **step** (constant from the first test period) is the simplest defensible
assumption; ramp/delayed-start/decay are documented later options that must be agreed
before implementation (PA-FR3).

### 4.6 Autocorrelation handling

AR(1) on pre-period residuals (Cochrane–Orcutt-style) is implemented. Higher ρ widens
the null and lowers power. **Caution:** ρ̂ from ~120 weekly periods carries sampling
error (observed ~0.24 vs truth 0.40 for one seed), which shifts the power curve by a
few points — this is inherent and should be surfaced as a limitation (or mitigated by
requiring more pre-period data, see 4.12).

### 4.7 Rolling-origin or placebo windows

Placebo windows provide an empirical null (the legacy method). Model-based simulation
uses the full pre-period residual process instead, which is more data-efficient.
Recommendation: primary = model simulation; placebo windows retained as a diagnostic
cross-check (they also feed the existing placebo-based preview).

### 4.8 Finite-sample policy

The prototype enforces: minimum historical periods (default 12), minimum simulations
(default 100), minimum placebo windows (default 5) — with explicit warnings. This
policy must be confirmed for production; no silent substitution when it fails.

### 4.9 Simulation count

Power is a binomial detection rate; the Clopper–Pearson CI shrinks with `n_sim`
(measured: CI narrower at 3000 than 300). Recommendation: **1,000–3,000** simulations
for a first-release default (0.5–1 point MC error), with the count and seed recorded
in every result (PA-FR5).

### 4.10 MDE search bounds and tolerance

The spike documents bounds (default 0–50% relative) and tolerance (default 0.5%);
the search is grid + bisection and returns an explicit **not-reached** state when the
target power is not achieved within bounds. These defaults require confirmation, and
the bounds/tolerance must be recorded in the result (PA-FR6).

### 4.11 Uncertainty around estimated power

Every power estimate carries a Clopper–Pearson CI on the alternative detection count.
**The interval is CONDITIONAL Monte Carlo uncertainty**: it covers only the binomial
sampling error of the detection count given the fitted model and the threshold
estimated from an independent calibration sample. It is NOT an exact unconditional
interval — threshold-estimation uncertainty is not included (measured: the empirical
power can sit above the analytic power by more than the CI width at moderate effects).
An outer repeated-calibration/bootstrap design is a documented production-stage option
if an unconditional interval is required. The CI must be surfaced in the UI/export so
power is never shown as a single unqualified number, and it must be labelled as
conditional.

### 4.12 Minimum historical data

The prototype warns below 12 pre-periods. For a stable AR(1)/power estimate the
evidence suggests **≥ 24–52 periods** is preferable; the exact production floor is an
open decision (PA-FR8) and should be set with real data in mind.

### 4.13 Fallback-fit policy

If the counterfactual design is underdetermined, rank-deficient, ill-conditioned or
empty, the prototype falls back to a constant-mean counterfactual. The fallback is
activated only by that explicit rule; the reason is recorded in
`matrix_diagnostics.fallback_reason`, `fit_status='fallback_constant_mean'`, and a
structured warning is emitted. A fallback is never silently substituted.

### 4.14 Default market shares and durations

**Open.** The spike does not cover market-share or duration *scenarios* (PA-FR7 —
"required market share or duration"); those are later-implementation work. Defaults
for candidate share/duration grids should be defined when the power-analysis core is
built, after this methodology is approved.

## 5. Recommendations summary

1. **Primary method:** model-based counterfactual simulation with AR(1) residual paths;
   the fit method is to be chosen from the OLS / Elastic Net / LASSO comparison evidence
   (and Bayesian TBR) at the approval gate.
2. **Detection:** interval excludes zero (one-sided default, two-sided available),
   recorded per result; only implemented criteria are accepted.
3. **Injection:** relative first, absolute supported, recorded per result; effect
   magnitude non-negative with direction from `side`.
4. **Shape:** step only in the service for first release; ramp and others are future options.
5. **Power uncertainty:** Clopper–Pearson CI on every estimate, labelled CONDITIONAL
   Monte Carlo uncertainty; 1,000–3,000 simulations.
6. **MDE:** grid + bisection with documented bounds/tolerance and explicit not-reached;
   MDE reported as a non-negative magnitude.
7. **Autocorrelation:** AR(1) fit with a stated limitation on ρ̂ estimation error.
8. **Placebo windows:** cross-check only, not the primary method; minimum windows
   enforced with an explicit incomplete result.
9. **Minimum data / fallback / finite-sample policy:** explicit warnings, recorded
   fallback reasons, no silent substitution.

## 6. Explicitly out of scope (must not be implemented from this spike)

- Production power UI (Mode A/B/C), platform, budget, delivery, or effect-plausibility UI.
- `feature/power-analysis-core`, `feature/power-analysis-ui`, `feature/platform-profile-schema`,
  `feature/media-delivery-feasibility`, `feature/effect-plausibility-scenarios`, or
  `feature/integrated-design-recommendation` — these are **later** branches that require
  this methodology to be approved first.
- Treating the existing `compute_power_curve` / `find_mde` closed-form placebo preview as
  an approved method without explicit review.

## 7. Corrections applied (Stage 1 — `fix/power-spike-correctness`)

PR #24 merged with unresolved correctness findings. This correction stage added failing
tests first and resolved every finding. Status remains **For methodology approval**; no
ADR is created.

| Finding | Correction |
|---|---|
| Negative-effect MDE | Effect magnitude is always non-negative; direction is controlled by `side` (`one_sided_negative` injects a negative shift from a positive magnitude). MDE is always reported as a non-negative magnitude. Tested for positive, negative and two-sided MDE. |
| Detection criteria | Only implemented criteria are accepted: `interval_excludes_zero` (all methods); `empirical_placebo_threshold` (placebo method only, rejected otherwise); `sign_and_threshold` rejected until a threshold field and implementation exist. A criterion is never exported unless applied. |
| Effect shape | The service supports `step` only; `ramp` is rejected until a real ramp simulation path exists (the generator's ramp is fixtures-only). This report no longer claims service-level ramp support. |
| Independent calibration / detection / diagnostics | Monte-Carlo methods use three independent streams (`rng.spawn(3)`): threshold calibration, alternative simulation, diagnostics. Reported uncertainty is defined as conditional Monte Carlo (see 4.11). |
| Rank deficiency | The design is checked for observations, predictor count, matrix rank, condition number, constant and duplicate predictors. A constant-mean fallback is activated only by an explicit rule (underdetermined / rank-deficient / ill-conditioned / no observations), with the reason recorded in `matrix_diagnostics` and a structured warning. |
| Empty placebo evidence | An empty placebo sample is never replaced with `[0.0]`. `min_placebo_windows` is enforced: insufficient placebo (or bootstrap residual) evidence produces an explicit incomplete result (`completed=false`, `minimum_window_status='insufficient'`, no MDE) with structured errors and blockers. |
| Date alignment | Regional series are aligned on a date-keyed matrix, reporting dates expected/retained/removed, controls with missing dates, duplicate region-date keys, and continuity. Missing, duplicated, shuffled and unequal-length regions are tested. |
| Explicit selected design | The service requires explicit `test_regions` and `control_regions` (plus optional planned `test_dates`); the hardcoded one-test-region assumption is removed (the `TEST_REGION` constant remains only in fixtures). Multiple test regions are aggregated by summing KPI per date, matching the evaluation workflow. |
| Method alignment | The spike's OLS counterfactual fit is compared with Elastic Net and LASSO on controlled cases (collinearity, many weak controls, short history, omitted controls, autocorrelated residuals). Evidence is recorded (see section 8) and presented for approval; no production method is auto-selected. |
| Result contract | `PowerResult` now carries `completed`, `fit_status`, `fit_method`, `matrix_diagnostics`, `calibration_simulations`, `detection_simulations`, `minimum_history_status`, `minimum_window_status`, `methodology_version`, `errors` and `blockers`. Critical failure states are no longer represented only as warning strings. |

## 8. Fit-method comparison evidence (PA-FR2)

The spike fits counterfactuals with unrestricted OLS, while the live application
evaluates with Elastic Net, LASSO and Bayesian TBR. `geotestlab/power/fit_comparison.py`
scores OLS, Elastic Net and LASSO on controlled cases (baseline, collinearity, many
weak controls, short history, omitted control, autocorrelated residuals) and records,
per method: counterfactual-sum error vs the known truth, residual sd, matrix
rank/condition number, fallback status, and power-at-reference-effect error vs the
analytic power. The comparison is deterministic (the same seed is used across methods,
so any power difference reflects the fit method alone). It is **evidence for approval,
not a selection**.

Open decision: choose the production counterfactual fit method after reviewing this
evidence (and the Bayesian TBR option) at the Stage 5 approval gate.

## 9. Realistic market-shaped evidence (Stage 4 — `test/power-methodology-realistic-evidence`)

Stage 1–2 corrections validated the prototype on **controlled** cases whose
counterfactual is an exact linear combination of controls and whose noise is pure
AR(1). That is too easy: the counterfactual is recoverable exactly and the power
curve saturates at 1 for effects above ~1%. This stage builds **realistic
market-shaped synthetic data** — weekday seasonality, multiple test regions,
tracking outages, low-volume KPIs, collinear / weak / duplicate controls, high
autocorrelation, heteroskedasticity, seasonal residuals, and an MDE that is never
reached — and runs all three candidate methods × three fit methods against a
**reference power computed from the known generative process** (no model fitting), so
the evidence isolates each method's estimation error.

The harness is `geotestlab/power/market_evidence.py` (deterministic; the committed
report regenerates byte-identically via `python scripts/update_market_evidence.py
--approve`). The full report (228 runs, ~60 s locally) is committed at
`docs/spikes/evidence/power-methodology-evidence.json`; the `@pytest.mark.slow` test
`test_full_evidence_report_matches_committed` guards it. Reference effects are chosen
so reference power sits in a discriminating 0.26–0.67 range.

### 9.1 Scenario inventory

| Scenario | Shape | Reference power (at ref. effect) | Reference MDE reached? |
|---|---|---|---|
| `weekly_52/104/156` | 52/104/156 weekly pre-periods, 2 test regions, 4 controls, AR(1) ρ=0.4, σ=2 | 0.626 / 0.644 / 0.668 | yes |
| `daily_weekday` | 365 daily pre-periods, weekday seasonality in controls + test-specific offsets, 6 tracking-outage dates, 2 test regions | 0.464 | yes |
| `low_volume` | small KPI (absolute injection; relative ill-defined) | 0.428 | yes |
| `high_autocorrelation` | ρ=0.9 | 0.336 | yes |
| `heteroskedastic` | noise sd scales with KPI level | 0.341 | yes |
| `seasonal_residuals` | weekend innovation sd ~2.5× weekdays | 0.394 | yes |
| `collinear_controls` | C2 near-duplicate of C1 (ill-conditioned, full rank) | 0.632 | yes |
| `many_weak_controls` | 8 weak controls | 0.505 | yes |
| `duplicate_controls` | C2 exactly duplicates C1 (rank rule → constant-mean fallback) | 0.632 | yes |
| `mde_not_reached` | near-unit-root ρ=0.99, large noise | 0.255 | **no** |

### 9.2 Null calibration (false-positive rate at effect 0, α=0.05)

`model_simulation` calibrates to α across every scenario (0.051–0.060).
`placebo_empirical` is **inflated** with few windows (0.125 with 8 windows — the
empirical threshold sits near the sample maximum), and `weekly_52` yields only 4
windows so placebo returns an explicit **incomplete** result (6 of the 228 runs).
This is evidence that placebo-window empirical power is a **cross-check only** and
that short histories cannot support 12-period placebo windows.

### 9.3 Power calibration (estimated − reference power at the reference effect)

`model_simulation` (OLS fit):

| Scenario | bias | Interpretation |
|---|---|---|
| `weekly_104` | **+0.012** | near-exact under adequate history |
| `weekly_156` | +0.050 | |
| `weekly_52` | **+0.306** | ρ̂ collapses to 0.07 (truth 0.4) at 52 weeks → null too narrow → power overestimated |
| `daily_weekday` | **−0.195** | unmodeled weekday offsets inflate residual σ̂ (4.6 vs 2.8) → null too wide → power underestimated |
| `low_volume` | +0.572 | overfit residuals → null too narrow (see 9.7) |
| `high_autocorrelation` | +0.238 | ρ̂=0.86 < truth 0.90 → null too narrow |
| `heteroskedastic` | +0.130 | constant-σ AR(1) misses level-scaled variance |
| `seasonal_residuals` | −0.028 | well captured by the fitted residual sd |
| `collinear_controls` | −0.036 | |
| `many_weak_controls` | −0.052 | |
| `duplicate_controls` | **−0.540** | constant-mean fallback discards the controls (see 9.7) |
| `mde_not_reached` | **+0.707** | ρ̂=0.90 < truth 0.99 → null sd ~4× too small → false power |

`residual_simulation` consistently **overestimates** power (+0.17 to +0.44):
bootstrapping residuals ignores autocorrelation, so the null is too narrow whenever
ρ>0. `placebo_empirical` also overestimates (+0.14 to +0.31) and cannot handle
absolute injection (raises a documented `NotImplementedError`, surfaced as a failure
mode in the report).

### 9.4 MDE bias and the not-reached failure mode

For `model_simulation` on `weekly_104`, MDE = 1.25 vs reference 1.0 (bias +0.25, i.e.
≤ the 0.5 tolerance). The critical failure mode is **near-unit-root autocorrelation**
(`mde_not_reached`): the TRUE process never reaches 80% power within the 50% bounds
(reference MDE = none), but the fitted AR(1) under-estimates persistence and reports a
reachable MDE (15.3, null sd ~264 vs true ~1005). The evidence surfaces this
disagreement explicitly — a near-unit-root series must be flagged, not silently
reported as having an MDE.

### 9.5 Seed and history sensitivity

Power-at-reference across two seeds: std 0.009–0.029 (`model_simulation`). History
matters more than seed: ρ̂ = 0.07 / 0.41 / 0.35 for 52 / 104 / 156 weekly periods
(truth 0.4) and power bias = +0.31 / +0.01 / +0.05. **A 52-week history is not enough**
for the AR(1) noise model; the evidence supports the ≥ 104-week production floor
(see 4.12) and a hard floor below which the power estimate must be flagged.

### 9.6 Fit-method comparison on market shapes (OLS vs Elastic Net vs LASSO)

On every market scenario the three fit methods are **indistinguishable** (power
differences < 0.01): with a well-specified counterfactual (exact linear combination)
the regularisation has nothing to shrink. Fit-method differences appear only when the
design is ill-conditioned, which the controlled cases in section 8 already document
(near-collinear OLS instability). `duplicate_controls` is the one market shape where
the fit method is irrelevant in a different sense: the explicit rank rule fires for
**all three** methods (12 of 228 runs fall back) and the constant-mean fallback
collapses power (0.09 vs 0.63 reference). **No production fit method is selected by
this evidence.**

### 9.7 Failure modes and fallback evidence

- **Fallback (12 runs):** `duplicate_controls` → `fallback_reason='rank_deficient'`
  for OLS, Elastic Net and LASSO; power collapses to 0.09 (vs 0.63) and MDE inflates
  to 5.5 (vs 1.1). The explicit rule prevents silent minimum-norm garbage.
- **Incomplete (6 runs):** `weekly_52` placebo → 4 windows < 5 → `completed=false`,
  no MDE, structured error + blocker.
- **Errored (6 runs):** placebo × absolute injection (`low_volume`) → documented
  `NotImplementedError` recorded as a failure mode.
- **Runtime:** the full 228-run matrix took ~61 s locally (≈0.27 s/run at n_sim=500,
  16-point effect grid); runtime is excluded from the committed report (non-
  deterministic) and reported here.

### 9.8 What this evidence adds to the methodology decision

1. `model_simulation` remains the best-calibrated primary method on realistic shapes
   (weekly_104 bias +0.01; the controlled cases already validated it ≤0.03 vs
   analytic power).
2. **Minimum history must be ≥ 104 weekly periods** (or equivalent daily) — 52 weeks
   breaks the AR(1) noise model (power bias +0.3).
3. Near-unit-root series must be **flagged**, not reported with a false MDE.
4. Daily data with unmodeled weekday seasonality biases power **down**; seasonality
   must be part of the counterfactual/design, not left in the residual.
5. `residual_simulation` and `placebo_empirical` are cross-checks, not primaries:
   both overestimate power under autocorrelation and placebo cannot do absolute
   injection or short histories.
6. Fit-method choice (OLS/EN/LASSO) is second-order for well-specified designs; the
   explicit fallback rule is the real protection.

Status remains **For methodology approval**; this stage adds evidence only — no
production method is selected, no ADR is created. The evidence file
`docs/spikes/evidence/power-methodology-evidence.json` is the source of the numbers
above and must be regenerated deliberately (script, not CI) if the methodology or
scenario definitions change.
