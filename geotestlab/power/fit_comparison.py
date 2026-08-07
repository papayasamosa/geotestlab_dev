"""Controlled fit-method comparison (power-spike correction).

The spike's counterfactual fit is unrestricted OLS, but the live application
evaluates with Elastic Net, LASSO and Bayesian TBR (PA-FR2). This module
produces decision evidence by comparing OLS, Elastic Net and LASSO
counterfactual fits on controlled synthetic cases (collinearity, many weak
controls, short history, omitted controls, autocorrelated residuals). It does
NOT select a production method — the evidence is presented for methodology
approval (see ``docs/spikes/power-analysis-methodology.md``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from geotestlab.power.detection import critical_values
from geotestlab.power.methods import (
    FIT_METHOD_NAMES,
    fit_counterfactual,
    model_simulation,
    project_counterfactual,
)
from geotestlab.power.synthetic import (
    analytic_power,
    analytic_total_variance,
    generate_synthetic_case,
)

CONTROLLED_FIT_SCENARIOS = (
    "baseline",
    "collinearity",
    "many_weak_controls",
    "short_history",
    "omitted_control",
    "autocorrelated_residuals",
    "irrelevant_controls",
    "nonlinear_relation",
    "time_varying_coefficients",
    "trend_seasonal_misspecification",
    "measurement_noise",
    "structural_breaks",
    "signal_to_noise_shifts",
)


def _test_kpi_mask(df):
    return df["region"] == "T"


def _apply_test_delta(df, delta_by_period):
    """Add ``delta_by_period[t]`` (t = 0-based row order) to the test
    region's kpi, in place, returning the mutated frame."""
    df = df.copy()
    mask = _test_kpi_mask(df)
    idx = df.index[mask]
    ordered = df.loc[idx].sort_values("date").index
    df.loc[ordered, "kpi"] = df.loc[ordered, "kpi"].to_numpy() + np.asarray(delta_by_period)
    return df


def _misspecified_case(base_case_kwargs, kind, seed):
    """Build a base linear/AR(1) synthetic case, then introduce a SPECIFIC
    misspecification the fit is blind to. ``base_case_kwargs["truth"]``
    (cf_sum_test, rho, sigma) is left UNCHANGED -- it is what a correctly
    specified linear fit would recover, so the fit-comparison evidence
    directly measures how far each method's estimated counterfactual drifts
    from that reference under each misspecification.
    """
    case = generate_synthetic_case(**base_case_kwargs)
    n_total = len(case.cf)
    t = np.arange(n_total, dtype=float)
    rng = np.random.default_rng(seed + 9000)

    if kind == "irrelevant_controls":
        # Pure-noise controls with NO relationship to the test region,
        # appended alongside the real predictive ones.
        dates = sorted(pd.to_datetime(pd.Series(case.df["date"].unique())))
        extra_rows = []
        for name in ("J1", "J2", "J3"):
            junk = rng.normal(0.0, 5.0, len(dates)) + 20.0
            for d, v in zip(dates, junk, strict=True):
                extra_rows.append({"date": d, "region": name, "kpi": float(v)})
        case.df = pd.concat([case.df, pd.DataFrame(extra_rows)], ignore_index=True)
        return case, ("C1", "C2", "J1", "J2", "J3")

    if kind == "nonlinear_relation":
        # True relationship to C1 is quadratic, not linear; C1's OWN series
        # (from case.df) drives the extra nonlinear term.
        c1 = case.df[case.df["region"] == "C1"].sort_values("date")["kpi"].to_numpy()
        gamma = 0.15
        delta = gamma * (c1 - np.mean(c1)) ** 2
        case.df = _apply_test_delta(case.df, delta)
        return case, ()

    if kind == "time_varying_coefficients":
        # The true coefficient on C1 drifts linearly across history instead
        # of staying fixed -- a single static linear fit cannot capture it.
        c1 = case.df[case.df["region"] == "C1"].sort_values("date")["kpi"].to_numpy()
        drift = np.linspace(-0.6, 0.6, n_total)
        delta = drift * c1
        case.df = _apply_test_delta(case.df, delta)
        return case, ()

    if kind == "trend_seasonal_misspecification":
        # An independent trend + seasonal component no control spans.
        delta = 0.08 * t + 4.0 * np.sin(2 * np.pi * t / 13.0)
        case.df = _apply_test_delta(case.df, delta)
        return case, ()

    if kind == "measurement_noise":
        # Controls observed with extra measurement error (attenuation
        # bias): the counterfactual truth used the CLEAN controls, but the
        # fit only sees noisy ones.
        df = case.df.copy()
        for region in ("C1", "C2"):
            mask = df["region"] == region
            df.loc[mask, "kpi"] = df.loc[mask, "kpi"].to_numpy() + rng.normal(
                0.0, 3.0, int(mask.sum())
            )
        case.df = df
        return case, ()

    if kind == "structural_breaks":
        # A discrete regime change in the C1 relationship partway through
        # history (not a gradual drift).
        c1 = case.df[case.df["region"] == "C1"].sort_values("date")["kpi"].to_numpy()
        break_point = n_total // 2
        extra_coef = np.where(t < break_point, 0.0, 1.5)
        delta = extra_coef * c1
        case.df = _apply_test_delta(case.df, delta)
        return case, ()

    if kind == "signal_to_noise_shifts":
        # Extra AR(1)-independent noise that is large in the first half of
        # history and small in the second half.
        extra_sd = np.where(t < n_total / 2, 6.0, 0.5)
        delta = rng.normal(0.0, 1.0, n_total) * extra_sd
        case.df = _apply_test_delta(case.df, delta)
        return case, ()

    raise ValueError(f"unknown misspecification kind {kind!r}")


def build_fit_scenario(name, seed=0):
    """Build ``(case, test_regions, fit_control_regions)`` for one scenario."""
    if name == "baseline":
        case = generate_synthetic_case(
            n_pre=120,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        return case, ("T",), ("C1", "C2")
    if name == "collinearity":
        # C1 and C2 share one near-common signal -> ill-conditioned design.
        case = generate_synthetic_case(
            n_pre=120,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1e-6,
        )
        return case, ("T",), ("C1", "C2")
    if name == "many_weak_controls":
        controls = {f"C{i}": 0.5 for i in range(1, 7)}
        coeffs = {f"C{i}": 0.25 for i in range(1, 7)}
        case = generate_synthetic_case(
            n_pre=120,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas=controls,
            test_coeffs=coeffs,
            b0=100.0,
            seed=seed,
            base_controls={f"C{i}": 10.0 for i in range(1, 7)},
            sd_control_noise=1.0,
        )
        return case, ("T",), tuple(f"C{i}" for i in range(1, 7))
    if name == "short_history":
        case = generate_synthetic_case(
            n_pre=20,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        return case, ("T",), ("C1", "C2")
    if name == "omitted_control":
        case = generate_synthetic_case(
            n_pre=120,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        return case, ("T",), ("C1",)  # C2 deliberately omitted from the fit
    if name == "autocorrelated_residuals":
        case = generate_synthetic_case(
            n_pre=120,
            n_test=12,
            rho=0.8,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        return case, ("T",), ("C1", "C2")
    if name in (
        "irrelevant_controls",
        "nonlinear_relation",
        "time_varying_coefficients",
        "trend_seasonal_misspecification",
        "measurement_noise",
        "structural_breaks",
        "signal_to_noise_shifts",
    ):
        base_kwargs = dict(
            n_pre=120,
            n_test=12,
            rho=0.4,
            sigma=2.0,
            control_betas={"C1": 1.0, "C2": 2.0},
            test_coeffs={"C1": 1.5, "C2": 0.5},
            b0=100.0,
            seed=seed,
            base_controls={"C1": 10.0, "C2": 10.0},
            sd_control_noise=1.0,
        )
        case, extra_controls = _misspecified_case(base_kwargs, name, seed)
        fit_controls = extra_controls if name == "irrelevant_controls" else ("C1", "C2")
        return case, ("T",), fit_controls
    raise ValueError(f"unknown fit scenario {name!r}")


def compare_fit_methods(
    case,
    test_regions,
    fit_control_regions,
    scenario="custom",
    fit_methods=FIT_METHOD_NAMES,
    seed=42,
    n_sim=500,
    reference_effect=1.0,
    alpha=0.05,
):
    """Fit each method on the case pre-period and score it against the truth.

    Returns a JSON-safe dict with per-method counterfactual error, residual sd,
    matrix diagnostics, and power-at-reference-effect evidence versus the
    analytic power under the known truth. Evidence only — no method is chosen.
    """
    pre_count = case.pre_count
    dates = sorted(pd.to_datetime(pd.Series(case.df["date"].unique())))
    pre_dates = set(dates[:pre_count])
    pre_df = case.df[case.df["date"].isin(pre_dates)]
    test_df = case.df[~case.df["date"].isin(pre_dates)]
    n_test = int(len(dates) - pre_count)

    truth_cf = float(case.truth["cf_sum_test"])
    sd_truth = float(
        np.sqrt(analytic_total_variance(case.truth["rho"], case.truth["sigma"], n_test))
    )
    shift_truth = truth_cf * reference_effect / 100.0
    analytic = analytic_power(truth_cf, sd_truth, shift_truth, alpha, "one_sided_positive")

    out = {
        "scenario": scenario,
        "truth_cf_sum_test": truth_cf,
        "reference_effect_pct": float(reference_effect),
        "analytic_power_at_reference": analytic,
        "results": [],
    }
    for m in fit_methods:
        fit = fit_counterfactual(pre_df, test_regions, fit_control_regions, fit_method=m)
        cf_test, _, _ = project_counterfactual(fit, test_df, test_regions, fit_control_regions)
        cf_sum = float(np.sum(cf_test))
        cf_err = (cf_sum - truth_cf) / truth_cf * 100.0 if truth_cf else float("nan")

        # Power-level evidence using this fit method's noise model. The same
        # seed is used for every method so the random streams are identical and
        # any power difference reflects the fit method alone. This is fit-method
        # comparison EVIDENCE, not a gated power-analysis result, and
        # deliberately exercises short-history/rank-deficient scenarios, so the
        # methodology safety policy (Stage 3) is not enforced here.
        cal_null, alt_fn, _ = model_simulation(
            pre_df,
            test_df,
            test_regions,
            fit_control_regions,
            n_test,
            n_sim,
            seed,
            fit_method=m,
            enforce_safety=False,
        )
        alt, _ = alt_fn(reference_effect, "relative", "one_sided_positive")
        lower, upper = critical_values(cal_null, "one_sided_positive", alpha)
        power_est = float(np.mean(alt > upper)) if len(alt) else float("nan")

        out["results"].append(
            {
                "fit_method": m,
                "cf_sum_error_pct": cf_err,
                "residual_sd": float(np.std(fit.residuals)) if len(fit.residuals) else None,
                "fit_status": fit.fit_status,
                "fallback_reason": fit.diagnostics.get("fallback_reason"),
                "matrix_rank": fit.diagnostics.get("matrix_rank"),
                "n_predictors": fit.diagnostics.get("n_predictors"),
                "condition_number": fit.diagnostics.get("condition_number"),
                "power_at_reference": power_est,
                "power_error_vs_analytic": power_est - analytic,
                "warning": fit.warnings[0] if fit.warnings else None,
            }
        )
    return out


# Deliberately tiny sampling profile: this is a BOUNDED, evidence-only
# comparison (never the production Bayesian MCMC profile). Matches
# tests/test_bayesian_core.py::TestReducedSamplingSmoke's reduced-sampling
# execution-path smoke test, not evidence of production MCMC convergence.
BAYESIAN_EVIDENCE_DRAWS = 20
BAYESIAN_EVIDENCE_TUNE = 10
BAYESIAN_EVIDENCE_CHAINS = 1


def compare_bayesian_evidence(case, test_regions, control_regions, seed=42):
    """Bounded Bayesian TBR comparison (EVIDENCE ONLY -- never auto-selected).

    Runs the REAL application Bayesian TBR service
    (``geotestlab.bayesian.service.run_bayesian``) on the SAME controlled
    synthetic case used for OLS/Elastic Net/LASSO in
    :func:`compare_fit_methods`, with a deliberately tiny MCMC sampling
    profile (draws=20, tune=10, chains=1) so this stays fast and bounded --
    it is NOT the production sampling profile and the result is NOT evidence
    of MCMC convergence. Uses a flat (non-structural) prior since there is no
    real structural/matching data for a synthetic case.

    This module never selects a production counterfactual-fit method; the
    Bayesian result is reported purely as comparison evidence alongside
    OLS/Elastic Net/LASSO for methodology approval.
    """
    from geotestlab.bayesian.models import BayesianConfig
    from geotestlab.bayesian.service import run_bayesian
    from geotestlab.validation.frequency import get_frequency_config

    dates = sorted(pd.to_datetime(pd.Series(case.df["date"].unique())))
    pre_start, pre_end = dates[0], dates[case.pre_count - 1]
    test_start, test_end = dates[case.pre_count], dates[-1]

    all_regions = list(test_regions) + list(control_regions)
    structural_agg_df = pd.DataFrame(
        {"region": all_regions, "Population": [10.0] * len(all_regions)}
    )

    config = BayesianConfig(
        method_name="power-fit-comparison-evidence",
        control_list=tuple(control_regions),
        test_regions=tuple(test_regions),
        geo_col="region",
        feature_cols=(),
        time_series_frequency="weekly",
        frequency_config=get_frequency_config("weekly"),
        include_lagged_controls=False,
        use_structural_priors=False,
        use_ar1_errors=True,
        pre_start=pre_start,
        pre_end=pre_end,
        test_start=test_start,
        test_end=test_end,
        use_post=False,
        mcmc_draws=BAYESIAN_EVIDENCE_DRAWS,
        mcmc_tune=BAYESIAN_EVIDENCE_TUNE,
        mcmc_chains=BAYESIAN_EVIDENCE_CHAINS,
        mcmc_target_accept=0.9,
        mcmc_random_seed=seed,
    )
    result = run_bayesian(case.df, structural_agg_df, config, selected_metric="kpi")

    truth_cf = float(case.truth["cf_sum_test"])
    note = (
        f"bounded evidence-only comparison (draws={BAYESIAN_EVIDENCE_DRAWS}, "
        f"tune={BAYESIAN_EVIDENCE_TUNE}, chains={BAYESIAN_EVIDENCE_CHAINS}); "
        "NOT the production MCMC profile, NOT auto-selected"
    )
    if not result.completed:
        return {
            "fit_method": "bayesian",
            "completed": False,
            "errors": list(result.errors),
            "blockers": list(result.blockers),
            "note": note,
        }
    cf_sum = float(np.sum(result.y_pred_test_mean))
    cf_err = (cf_sum - truth_cf) / truth_cf * 100.0 if truth_cf else float("nan")
    return {
        "fit_method": "bayesian",
        "completed": True,
        "cf_sum_error_pct": cf_err,
        "n_divergences": result.n_divergences,
        "rho_mean": result.rho_mean,
        "note": note,
    }
