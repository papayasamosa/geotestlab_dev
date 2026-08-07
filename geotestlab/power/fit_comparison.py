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
)


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
