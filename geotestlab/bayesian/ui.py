"""MCMC diagnostics rendering for the Bayesian TBR results view.

Extracted from the ``geotestmatch.py`` monolith in PR9 (legacy UI deletion
and bootstrap cleanup).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from geotestlab.bayesian.diagnostics import summarize_mcmc_diagnostics


def render_mcmc_diagnostics(bayes: dict, trace, *, ess_min_threshold: int) -> None:
    """Render MCMC diagnostics from a posterior trace.

    Called only when ``trace`` is present — the caller guards rendering when the
    trace is missing (e.g. after a reset or a file change), so the large
    ``InferenceData`` object can be dropped without crashing the results view.

    ``ess_min_threshold`` is supplied by the caller (the app's ``CONFIG``) so
    this module stays free of app-level config.
    """
    import arviz as az

    _summary_vars = ["intercept", "coeffs", "sigma"] + (
        ["rho"] if bayes.get("use_ar1_errors") else []
    )
    summary = az.summary(trace, var_names=_summary_vars, hdi_prob=0.94)
    _mcmc_n_chains = bayes.get("n_chains")
    _mcmc_n_draws = bayes.get("n_draws")
    _mcmc_n_tune = bayes.get("n_tune")
    _mcmc_target_accept = bayes.get("target_accept")
    _mcmc_n_total_draws = (
        _mcmc_n_chains * _mcmc_n_draws if _mcmc_n_chains and _mcmc_n_draws else None
    )
    diag = summarize_mcmc_diagnostics(
        summary,
        n_divergences=bayes.get("n_divergences"),
        n_total_draws=_mcmc_n_total_draws,
        ess_min_threshold=ess_min_threshold,
    )

    with st.expander("MCMC Diagnostics", expanded=True):
        st.markdown("**Diagnostic summary**")
        if _mcmc_n_chains is not None:
            st.caption(
                f"Sampled {_mcmc_n_chains} chains × {_mcmc_n_draws} draws "
                f"({_mcmc_n_tune} tuning steps), target_accept={_mcmc_target_accept}."
            )
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric(
            "Chain convergence",
            f"{'✅ Pass' if diag['rhat_ok'] else '⚠️ Warning'}",
            help=(
                f"R-hat measures whether the sampling chains converged on the same distribution. "
                f"Values close to 1.0 mean convergence. Above 1.01 suggests the chains disagreed — "
                f"results may be unreliable.\n\nYour max R-hat: {diag['max_rhat']:.3f} (pass = ≤1.01)."
            ),
        )
        col2.metric(
            "Effective sample size",
            f"{'✅ Pass' if diag['ess_ok'] else '⚠️ Warning'}",
            help=(
                f"ESS estimates how many independent samples your chains are equivalent to, "
                f"after accounting for autocorrelation. Higher is better. Low ESS means the "
                f"sampler got 'stuck' and posterior estimates may be noisy.\n\n"
                f"Your min ESS: {diag['min_ess']:.0f} (guidance = ≥{ess_min_threshold})."
            ),
        )
        col3.metric(
            "Sampling error",
            f"{'✅ Pass' if diag['mcse_ok'] else '⚠️ Warning'}",
            help=(
                f"MCSE (Monte Carlo Standard Error) measures numerical noise in the posterior mean "
                f"estimates relative to the posterior SD. Below 10% means the sampling error is "
                f"small compared to genuine uncertainty in the model.\n\n"
                f"Your max MCSE/SD: {diag['max_mcse_sd_ratio']:.1%} (pass = <10%)."
            ),
        )
        _divergence_help = (
            "Divergent transitions mean the sampler failed to explore a specific region of the "
            "posterior. Unlike the other three checks, this can bias point estimates rather than "
            "just add noise, so even one divergence is treated as a fail here.\n\n"
            f"Your divergences: {diag['n_divergences'] if diag['n_divergences'] is not None else 'N/A'}"
        )
        if diag["divergence_rate"] is not None:
            _divergence_help += f" ({diag['divergence_rate']:.1%} of draws)."
        col4.metric(
            "Divergences",
            f"{'✅ Pass' if diag['divergence_ok'] else '⚠️ Warning'}",
            help=_divergence_help,
        )
        col5.metric(
            "Overall status",
            diag["status"],
            help=(
                "All four diagnostics must pass for an overall Good status. "
                "A warning on any one of them means you should interpret results cautiously — "
                "try increasing draws, tuning steps, or target_accept if issues persist."
            ),
        )
        if diag["messages"]:
            for msg in diag["messages"]:
                st.warning(msg)

    # Kept as a sibling expander, not nested inside "MCMC Diagnostics" above —
    # Streamlit does not allow expanders to be nested inside other expanders.
    with st.expander("View full MCMC diagnostics table", expanded=False):
        rename_map = {
            "mean": "Mean",
            "sd": "SD",
            "hdi_3%": "94% lower",
            "hdi_97%": "94% upper",
            "mcse_mean": "MCSE mean",
            "mcse_sd": "MCSE SD",
            "ess_bulk": "ESS bulk",
            "ess_tail": "ESS tail",
            "r_hat": "R-hat",
        }
        existing_cols = [col for col in rename_map if col in summary.columns]
        display_summary = summary[existing_cols].rename(columns=rename_map).astype(float)
        for col in display_summary.columns:
            if col in ["ESS bulk", "ESS tail"]:
                display_summary[col] = display_summary[col].round(0)
            else:
                display_summary[col] = display_summary[col].round(3)
        # Replace coeffs[n] index labels with control region / lagged feature names
        coeff_feature_list = bayes.get("model_feature_cols") or bayes.get("control_list", [])
        new_index = []
        for idx in display_summary.index:
            if idx.startswith("coeffs[") and idx.endswith("]"):
                try:
                    n = int(idx[7:-1])
                    new_index.append(coeff_feature_list[n] if n < len(coeff_feature_list) else idx)
                except (ValueError, IndexError):
                    new_index.append(idx)
            else:
                new_index.append(idx)
        display_summary.index = new_index

        # ---- Row-level highlighting: flag which specific parameter(s) are driving
        # a "Review needed" status, rather than making the user scan manually. ----
        def _flag_bad_diagnostic_row(row):
            rhat = row.get("R-hat", np.nan)
            ess_bulk = row.get("ESS bulk", np.nan)
            ess_tail = row.get("ESS tail", np.nan)
            sd = row.get("SD", np.nan)
            mcse_mean = row.get("MCSE mean", np.nan)
            mcse_sd_ratio = (
                (mcse_mean / sd) if (pd.notna(sd) and sd != 0 and pd.notna(mcse_mean)) else np.nan
            )
            is_bad = (
                (pd.notna(rhat) and rhat > 1.01)
                or (pd.notna(ess_bulk) and ess_bulk < ess_min_threshold)
                or (pd.notna(ess_tail) and ess_tail < ess_min_threshold)
                or (pd.notna(mcse_sd_ratio) and mcse_sd_ratio >= 0.10)
            )
            return (
                ["background-color: #FEE2E2; color: #7F1D1D"] * len(row)
                if is_bad
                else [""] * len(row)
            )

        styled_summary = display_summary.style.apply(_flag_bad_diagnostic_row, axis=1)
        st.dataframe(styled_summary, width="stretch")
        if diag["n_divergences"]:
            st.caption(
                f"{diag['n_divergences']} divergent transition(s) occurred during sampling. "
                "Divergences aren't tied to a specific parameter row the way R-hat/ESS/MCSE are, "
                "so they aren't reflected in the highlighting above — see the Divergences card and "
                "warning above the table instead."
            )
        st.caption(
            "Rows highlighted in red fail at least one of: R-hat > 1.01, ESS bulk or tail "
            f"< {ess_min_threshold}, or MCSE/SD ≥ 10%."
        )
