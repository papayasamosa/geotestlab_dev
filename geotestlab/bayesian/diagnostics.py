"""MCMC diagnostic summarisation (pure; accepts a plain summary DataFrame)."""

from __future__ import annotations


def summarize_mcmc_diagnostics(
    summary_df, n_divergences=None, n_total_draws=None, ess_min_threshold=500
):
    """
    Compute high‑level MCMC diagnostics from an ArviZ summary DataFrame.

    Returns a dict with keys: max_rhat, min_ess, max_mcse_sd_ratio, n_divergences,
    divergence_rate, status, messages, and per-check boolean flags.

    n_divergences: total count of divergent transitions across all chains (from
    trace.sample_stats["diverging"].sum()), if available. n_total_draws: total
    post-tuning draws across all chains (chains * draws), used only to compute a
    display divergence rate. If n_divergences is None (not passed), the divergence
    check is skipped and treated as passing — callers should always pass it when
    available.

    Divergences are checked alongside R-hat/ESS/MCSE, not as a replacement for them:
    unlike those three (which mostly flag sampling *noise*), a divergence flags a
    specific region of the posterior the sampler failed to explore, which can bias
    point estimates rather than just add noise — so even a single divergence is
    treated as a hard fail here, unlike the other three which use tolerance bands.

    ``ess_min_threshold`` is provided by the caller (the app supplies its CONFIG
    value) so this module stays dependency-free.
    """
    summary_df = summary_df.astype(float)

    max_rhat = summary_df["r_hat"].max()
    min_ess = min(summary_df["ess_bulk"].min(), summary_df["ess_tail"].min())
    max_mcse_sd = (summary_df["mcse_mean"] / summary_df["sd"]).max()

    rhat_ok = bool(max_rhat <= 1.01)
    ess_ok = bool(min_ess >= ess_min_threshold)  # softer threshold
    mcse_ok = bool(max_mcse_sd < 0.10)
    divergence_ok = bool((n_divergences is None) or (n_divergences == 0))
    divergence_rate = (
        (n_divergences / n_total_draws) if (n_divergences is not None and n_total_draws) else None
    )

    overall_ok = rhat_ok and ess_ok and mcse_ok and divergence_ok
    status = "✅ Good" if overall_ok else "⚠️ Review needed"

    messages = []
    if not rhat_ok:
        messages.append(f"R‑hat > 1.01 (max = {max_rhat:.3f}) – chains may not have converged.")
    if not ess_ok:
        messages.append(
            f"Effective sample size < {ess_min_threshold} (min = {min_ess:.0f}) – try increasing draws/tune."
        )
    if not mcse_ok:
        messages.append(f"MCSE/SD > 10% (max = {max_mcse_sd:.1%}) – sampling error may be high.")
    if not divergence_ok:
        _rate_str = f" ({divergence_rate:.1%} of draws)" if divergence_rate is not None else ""
        messages.append(
            f"{n_divergences} divergent transition(s){_rate_str} – posterior estimates may be biased "
            "in the region the sampler avoided, not just noisier. Try a higher target_accept, more "
            "tuning steps, or reparameterizing the model."
        )

    return {
        "max_rhat": max_rhat,
        "min_ess": min_ess,
        "max_mcse_sd_ratio": max_mcse_sd,
        "n_divergences": n_divergences,
        "divergence_rate": divergence_rate,
        "rhat_ok": rhat_ok,
        "ess_ok": ess_ok,
        "mcse_ok": mcse_ok,
        "divergence_ok": divergence_ok,
        "overall_ok": overall_ok,
        "status": status,
        "messages": messages,
    }
