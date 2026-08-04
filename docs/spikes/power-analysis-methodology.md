# Power-Analysis Methodology Spike — Decision Evidence

**Document type:** Methodology spike report (decision evidence)
**Stage:** 5 — `spike/power-analysis-methodology`
**Date:** 4 August 2026
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
Controlled tests: `tests/test_power_spike.py` (32 tests).

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

All three are implemented (`one_sided_positive`, `one_sided_negative`, `two_sided`).
Two-sided power is strictly lower; a one-sided-negative test should not be used to
evaluate a positive-effect hypothesis. Recommendation: expose the side as an explicit
input; default to one-sided only when the effect direction is pre-specified.

### 4.4 Relative versus absolute effect injection

Both are implemented and validated. Relative injection (constant `%` uplift) is the
natural default for KPI readouts and matches the product spec's first-release option
(PA-FR3). Absolute injection is a constant per-period shift (useful for low-volume or
near-zero KPIs where a relative shift is ill-defined). Recommendation: **relative
first**, absolute supported, with the policy recorded in the result.

### 4.5 Effect shape

Step vs ramp are implemented in the synthetic generator. A ramp of peak `e` injects
≈ half the total effect of a step `e`. For first release, **step** (constant from the
first test period) is the simplest defensible assumption; ramp/delayed-start/decay are
documented later options that must be agreed before implementation (PA-FR3).

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

Every power estimate carries a Clopper–Pearson CI (validated to contain the analytic
power). The CI must be surfaced in the UI/export so power is never shown as a single
unqualified number.

### 4.12 Minimum historical data

The prototype warns below 12 pre-periods. For a stable AR(1)/power estimate the
evidence suggests **≥ 24–52 periods** is preferable; the exact production floor is an
open decision (PA-FR8) and should be set with real data in mind.

### 4.13 Fallback-fit policy

If the counterfactual OLS design is singular, the prototype falls back to a
constant-mean counterfactual and the result carries a warning. This policy is
recorded; a fallback must never be silently substituted without a warning.

### 4.14 Default market shares and durations

**Open.** The spike does not cover market-share or duration *scenarios* (PA-FR7 —
"required market share or duration"); those are later-implementation work. Defaults
for candidate share/duration grids should be defined when the power-analysis core is
built, after this methodology is approved.

## 5. Recommendations summary

1. **Primary method:** model-based counterfactual simulation with AR(1) residual paths.
2. **Detection:** interval excludes zero (one-sided default, two-sided available), recorded per result.
3. **Injection:** relative first, absolute supported, recorded per result.
4. **Shape:** step for first release; ramp and others are future options.
5. **Power uncertainty:** Clopper–Pearson CI on every estimate; 1,000–3,000 simulations.
6. **MDE:** grid + bisection with documented bounds/tolerance and explicit not-reached.
7. **Autocorrelation:** AR(1) fit with a stated limitation on ρ̂ estimation error.
8. **Placebo windows:** cross-check only, not the primary method.
9. **Minimum data / fallback / finite-sample policy:** explicit warnings, no silent fallback.

## 6. Explicitly out of scope (must not be implemented from this spike)

- Production power UI (Mode A/B/C), platform, budget, delivery, or effect-plausibility UI.
- `feature/power-analysis-core`, `feature/power-analysis-ui`, `feature/platform-profile-schema`,
  `feature/media-delivery-feasibility`, `feature/effect-plausibility-scenarios`, or
  `feature/integrated-design-recommendation` — these are **later** branches that require
  this methodology to be approved first.
- Treating the existing `compute_power_curve` / `find_mde` closed-form placebo preview as
  an approved method without explicit review.
