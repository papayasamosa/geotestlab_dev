"""Methodology safety policy for the power-analysis spike (Stage 3).

A green CI run, a completed :class:`~geotestlab.power.models.PowerResult` or
high test coverage is NOT proof that a statistical methodology is valid for a
given dataset. This module adds a typed, versioned safety policy that
evaluates six independent dimensions of the current constant-sigma AR(1)
counterfactual method against the ACTUAL retained data, and combines them
into one structured support verdict:

- ``frequency`` — is the KPI frequency one the current method supports at all;
- ``history`` — retained jointly-complete pre-period periods, calendar
  continuity and predictor count (not just the requested ``pre_count``);
- ``persistence`` — AR(1) rho and its estimation uncertainty; a plausible
  near-unit-root process must block, not merely warn, because the reported
  MDE would otherwise be unreliable;
- ``seasonality`` — daily-frequency data carries calendar structure the
  current residual model cannot represent;
- ``heteroskedasticity`` — a deterministic diagnostic on whether residual
  variance is stable across the fitted level;
- ``control_matrix`` — whether the counterfactual fit fell back to a
  constant mean, or which controls were sanitised away before fitting.

Every check returns ``(status, reasons, metrics)`` where ``status`` is one of
:data:`SUPPORTED`, :data:`SUPPORTED_WITH_WARNING`, :data:`UNSUPPORTED` or
:data:`BLOCKED`. :func:`evaluate_safety` combines them; the OVERALL status is
the most severe of the six, so a single blocking dimension blocks the whole
result even if every other dimension is clean.

This module does not change methodology approval status: it makes the
CURRENT (unapproved) spike refuse to report power/MDE where the evidence
shows the current method is unsafe, rather than reporting a plausible-looking
but misleading number.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from geotestlab.power.models import FREQUENCIES

SUPPORTED = "supported"
SUPPORTED_WITH_WARNING = "supported_with_warning"
UNSUPPORTED = "unsupported"
BLOCKED = "blocked"

SUPPORT_STATUSES = (SUPPORTED, SUPPORTED_WITH_WARNING, UNSUPPORTED, BLOCKED)

_SEVERITY = {SUPPORTED: 0, SUPPORTED_WITH_WARNING: 1, UNSUPPORTED: 2, BLOCKED: 3}

SAFETY_POLICY_VERSION = "0.2.0"


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass(frozen=True)
class MethodologySafetyPolicy:
    """Versioned, typed thresholds for the current AR(1) method's safety gates.

    Every threshold here is a policy DECISION, not a law of statistics — it is
    calibrated against ``docs/spikes/evidence/power-methodology-evidence.json``
    (see the critical findings this stage addresses) and is recorded on every
    result so a future policy change is auditable.
    """

    version: str = SAFETY_POLICY_VERSION
    # Frequencies the CURRENT constant-sigma AR(1) method supports outright.
    # "daily" is a recognised, typed frequency (see FREQUENCIES) that is
    # nonetheless blocked until an approved daily seasonal process exists.
    supported_frequencies: tuple = ("weekly",)
    # Minimum retained jointly-complete periods per frequency, below which
    # the result is BLOCKED outright. Calibrated from evidence showing 52
    # weekly periods carries a +0.306 power bias for the current method,
    # while 104 carries +0.012 and 156 carries +0.050 (both acceptable).
    min_history_periods: dict = field(default_factory=lambda: {"weekly": 104})
    # A history/predictor-count ratio below this triggers a warning (not a
    # block) that there may be too few periods per fitted predictor.
    min_periods_per_predictor: float = 10.0
    # Persistence: an approximate one-sided upper confidence bound on the
    # fitted AR(1) rho (rho_hat + persistence_z * se(rho_hat), se from the
    # standard OLS-autocorrelation approximation sqrt((1-rho^2)/n)) at or
    # above this threshold is treated as a plausible near-unit-root process
    # and BLOCKS the result, even when the point estimate itself is lower.
    # The v2 multi-seed study showed that rho~=0.9 is already materially
    # under-calibrated for the current short-horizon AR(1) simulation even
    # when the point estimate's upper bound is below 0.97.  Treat a plausible
    # rho >= 0.92 as unsupported by this spike; an approved production method
    # may choose a different persistence model after the ADR gate.
    persistence_near_unit_root_upper: float = 0.92
    persistence_z: float = 2.0
    # A point-estimate rho at or above this (but not near-unit-root) is a
    # warning: power/MDE are more sensitive to noise, not unreliable.
    persistence_warning_rho: float = 0.80
    # Heteroskedasticity: retain the split-variance candidate for continuity,
    # but combine it with a dependence-preserving scale-association test.
    # The latter permutes contiguous residual blocks against fitted levels,
    # preserving short-range autocorrelation instead of using iid residual
    # permutations.  The union is intentionally conservative: uncertainty
    # about a constant-variance assumption blocks the unapproved spike rather
    # than silently reporting optimistic power.
    heteroskedasticity_ratio_block: float = 2.3
    heteroskedasticity_scale_pvalue: float = 0.05
    heteroskedasticity_scale_min_abs_correlation: float = 0.15
    heteroskedasticity_block_length: int = 13
    heteroskedasticity_resamples: int = 199
    heteroskedasticity_random_seed: int = 20240814


DEFAULT_SAFETY_POLICY = MethodologySafetyPolicy()


def frequency_support(frequency: str, policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY):
    metrics = {"frequency": frequency}
    if frequency not in FREQUENCIES:
        return (
            UNSUPPORTED,
            [f"unknown frequency {frequency!r}; expected one of {FREQUENCIES}"],
            metrics,
        )
    if frequency not in policy.supported_frequencies:
        return (
            BLOCKED,
            [
                f"{frequency!r} frequency is not supported by the current constant-sigma "
                "AR(1) residual model (no seasonal/calendar component); blocked until an "
                "approved daily seasonal process exists. Weekly aggregation of daily data "
                "may be offered only as an explicit, separately recorded analyst decision, "
                "never a silent frequency change."
            ],
            metrics,
        )
    return SUPPORTED, [], metrics


def seasonality_support(frequency: str, policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY):
    if frequency == "daily":
        return (
            BLOCKED,
            [
                "daily-frequency data may carry weekday/calendar seasonality that the "
                "current constant-sigma AR(1) residual model cannot represent (calendar "
                "structure remains in the residuals and materially under-estimates power); "
                "blocked until an approved daily seasonal process exists"
            ],
            {},
        )
    return SUPPORTED, [], {}


def history_support(
    retained_periods: int,
    frequency: str,
    continuity: str,
    n_predictors: int,
    policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY,
):
    metrics = {"retained_periods": int(retained_periods), "continuity": continuity}
    min_periods = policy.min_history_periods.get(frequency)
    if min_periods is None:
        return (
            UNSUPPORTED,
            [f"no minimum-history floor configured for frequency {frequency!r}"],
            metrics,
        )
    metrics["min_periods"] = min_periods
    if retained_periods < min_periods:
        return (
            BLOCKED,
            [
                f"only {retained_periods} retained {frequency} periods (< required minimum "
                f"{min_periods} for the current AR(1) method; evidence shows an unacceptable "
                "power bias below this floor)"
            ],
            metrics,
        )
    reasons = []
    if continuity not in ("contiguous", "single_date"):
        reasons.append(f"pre-period date continuity is {continuity!r}, not fully contiguous")
    if n_predictors > 0 and retained_periods < n_predictors * policy.min_periods_per_predictor:
        reasons.append(
            f"only {retained_periods} retained periods for {n_predictors} predictors "
            f"(< {policy.min_periods_per_predictor:g}x periods-per-predictor rule of thumb)"
        )
    status = SUPPORTED_WITH_WARNING if reasons else SUPPORTED
    return status, reasons, metrics


def persistence_support(
    rho: float, n_periods: int, policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY
):
    if n_periods <= 1:
        return UNSUPPORTED, ["insufficient periods to estimate persistence uncertainty"], {}
    se = float(np.sqrt(max(1.0 - float(rho) ** 2, 0.0) / n_periods))
    rho_upper = float(rho) + policy.persistence_z * se
    metrics = {"rho": float(rho), "se_rho": se, "rho_upper": rho_upper}
    if rho_upper >= policy.persistence_near_unit_root_upper:
        return (
            BLOCKED,
            [
                f"persistence rho={rho:.3f} (se~{se:.3f}) has an approximate upper bound "
                f"{rho_upper:.3f} within the near-unit-root region "
                f"(>= {policy.persistence_near_unit_root_upper}); a plausible near-unit-root "
                "process would make the reported power/MDE unreliable"
            ],
            metrics,
        )
    reasons = []
    if rho >= policy.persistence_warning_rho:
        reasons.append(f"elevated persistence rho={rho:.3f}; power/MDE are more sensitive to noise")
    status = SUPPORTED_WITH_WARNING if reasons else SUPPORTED
    return status, reasons, metrics


def heteroskedasticity_support(
    residuals, level, policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY
):
    r = np.asarray(residuals, dtype=float)
    lvl = np.asarray(level, dtype=float)
    if len(r) < 8:
        return UNSUPPORTED, ["too few residuals to assess heteroskedasticity"], {}
    finite = np.isfinite(r) & np.isfinite(lvl)
    r = r[finite]
    lvl = lvl[finite]
    if len(r) < 8:
        return UNSUPPORTED, ["too few finite residuals to assess heteroskedasticity"], {}

    order = np.argsort(lvl)
    rr = r[order]
    n = len(rr)
    half = n // 2
    low, high = rr[:half], rr[n - half :]
    var_low = float(np.var(low, ddof=1)) if len(low) > 1 else 0.0
    var_high = float(np.var(high, ddof=1)) if len(high) > 1 else 0.0
    if var_low > 0:
        ratio = var_high / var_low
    else:
        ratio = float("inf") if var_high > 0 else 1.0
    upper = policy.heteroskedasticity_ratio_block
    lower = 1.0 / upper
    centered_sq = (r - float(np.mean(r))) ** 2
    level_centered = lvl - float(np.mean(lvl))
    denominator = float(np.sqrt(np.dot(level_centered, level_centered)))
    sq_centered = centered_sq - float(np.mean(centered_sq))
    sq_denominator = float(np.sqrt(np.dot(sq_centered, sq_centered)))
    scale_correlation = (
        float(np.dot(level_centered, sq_centered) / (denominator * sq_denominator))
        if denominator > 0 and sq_denominator > 0
        else 0.0
    )

    block_length = min(
        max(2, int(policy.heteroskedasticity_block_length)),
        max(2, len(r)),
    )
    blocks = [r[start : start + block_length] for start in range(0, len(r), block_length)]
    rng = np.random.default_rng(
        int(policy.heteroskedasticity_random_seed) + len(r) + int(np.round(np.sum(lvl)))
    )
    null_statistics = []
    for _ in range(max(1, int(policy.heteroskedasticity_resamples))):
        permuted = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])[: len(r)]
        permuted_sq = (permuted - float(np.mean(permuted))) ** 2
        permuted_centered = permuted_sq - float(np.mean(permuted_sq))
        permuted_denominator = float(np.sqrt(np.dot(permuted_centered, permuted_centered)))
        null_statistics.append(
            float(np.dot(level_centered, permuted_centered) / (denominator * permuted_denominator))
            if denominator > 0 and permuted_denominator > 0
            else 0.0
        )
    null_statistics = np.asarray(null_statistics, dtype=float)
    observed_abs = abs(scale_correlation)
    scale_pvalue = float(
        (1 + np.count_nonzero(np.abs(null_statistics) >= observed_abs)) / (len(null_statistics) + 1)
    )
    scale_candidate_blocks = bool(
        scale_pvalue <= policy.heteroskedasticity_scale_pvalue
        and observed_abs >= policy.heteroskedasticity_scale_min_abs_correlation
    )
    ratio_candidate_blocks = bool(not np.isfinite(ratio) or ratio >= upper or ratio <= lower)
    metrics = {
        "variance_ratio_high_over_low_level": ratio if np.isfinite(ratio) else None,
        "variance_low_level": var_low,
        "variance_high_level": var_high,
        "scale_association_correlation": scale_correlation,
        "scale_association_abs_correlation": observed_abs,
        "scale_association_block_permutation_pvalue": scale_pvalue,
        "scale_association_block_length": block_length,
        "scale_association_resamples": len(null_statistics),
        "candidate_diagnostics": {
            "split_variance_ratio": "blocked" if ratio_candidate_blocks else "supported",
            "block_permutation_scale_association": (
                "blocked" if scale_candidate_blocks else "supported"
            ),
        },
    }
    if ratio_candidate_blocks or scale_candidate_blocks:
        candidates = []
        if ratio_candidate_blocks:
            candidates.append(
                f"split variance ratio={ratio if np.isfinite(ratio) else 'inf'} "
                f"outside [{lower:.2f}, {upper:.2f}]"
            )
        if scale_candidate_blocks:
            candidates.append(
                "dependence-preserving scale association is material "
                f"(abs correlation={observed_abs:.3f}, permutation p={scale_pvalue:.3f})"
            )
        return (
            BLOCKED,
            ["; ".join(candidates) + "; constant-variance AR(1) simulation is blocked"],
            metrics,
        )
    return SUPPORTED, [], metrics


def control_matrix_support(fit_diagnostics: dict):
    # A constant-mean fallback is an ACCEPTED, already-reported degraded mode
    # (see fit_counterfactual's fallback_reason/warnings) when the design is
    # genuinely underdetermined/rank-deficient/ill-conditioned even AFTER
    # sanitising constant/duplicate controls -- it is not re-blocked here,
    # only flagged as a warning so the safety verdict is visible alongside
    # the existing fit-level warning.
    if fit_diagnostics.get("fallback_used"):
        return (
            SUPPORTED_WITH_WARNING,
            [
                "counterfactual fit fell back to a constant mean: "
                f"{fit_diagnostics.get('fallback_reason')}"
            ],
            {},
        )
    removed = fit_diagnostics.get("removed_controls") or []
    reasons = []
    if removed:
        reasons.append("sanitised " + ", ".join(f"{r['region']} ({r['reason']})" for r in removed))
    status = SUPPORTED_WITH_WARNING if reasons else SUPPORTED
    return status, reasons, {"removed_controls": removed}


def evaluate_safety(
    *,
    frequency: str,
    retained_periods: int,
    continuity: str,
    n_predictors: int,
    rho: float,
    fit_diagnostics: dict,
    residuals,
    level,
    policy: MethodologySafetyPolicy = DEFAULT_SAFETY_POLICY,
) -> dict:
    """Combine every safety dimension into one JSON-safe structured verdict.

    ``overall_status`` is the MOST SEVERE of the six sub-statuses: one
    blocking dimension blocks the whole result regardless of the others.

    Persistence and heteroskedasticity are diagnostics about a REAL
    counterfactual fit's residuals; when the fit fell back to a constant
    mean, "AR(1) persistence"/"heteroskedasticity" of mean-only residuals
    measures the raw series' own structure, not the counterfactual noise
    model's safety, and is not evaluated separately -- the fallback is
    already reported (as a warning, not a block) via control_matrix_status.
    """
    fallback_used = bool(fit_diagnostics.get("fallback_used"))
    if fallback_used:
        not_applicable = (SUPPORTED, [], {"note": "not evaluated: fit fell back to constant mean"})
        persistence_result = not_applicable
        heteroskedasticity_result = not_applicable
    else:
        persistence_result = persistence_support(rho, retained_periods, policy)
        heteroskedasticity_result = heteroskedasticity_support(residuals, level, policy)
    checks = {
        "frequency": frequency_support(frequency, policy),
        "history": history_support(retained_periods, frequency, continuity, n_predictors, policy),
        "persistence": persistence_result,
        "seasonality": seasonality_support(frequency, policy),
        "heteroskedasticity": heteroskedasticity_result,
        "control_matrix": control_matrix_support(fit_diagnostics),
    }
    overall = _worst(*(status for status, _reasons, _metrics in checks.values()))
    reasons = [
        f"{name}: {reason}"
        for name, (_status, reasons_, _metrics) in checks.items()
        for reason in reasons_
    ]
    result = {
        "policy_version": policy.version,
        "overall_status": overall,
        "reasons": reasons,
        "metrics": {name: metrics for name, (_status, _reasons, metrics) in checks.items()},
    }
    for name, (status, reasons_, _metrics) in checks.items():
        result[f"{name}_status"] = status
        result[f"{name}_reasons"] = reasons_
    return result
