"""Candidate power methods for the Stage 5 spike (PA-FR2 decision evidence).

Three candidate first-release methods are implemented against controlled
synthetic cases. Each returns ``(calibration_null, alt_fn, meta)``:

- ``calibration_null`` — the null sample used ONLY to estimate detection
  thresholds (threshold-calibration stream);
- ``alt_fn(effect, injection, side)`` — an INDEPENDENT alternative sample under
  an injected effect (independent alternative stream; called once per effect);
- ``meta`` — JSON-safe diagnostics, including null mean/sd estimated on a
  separate diagnostics stream, fit status, matrix diagnostics, window counts,
  simulation counts, failures and warnings.

Monte-Carlo methods use three independent random streams (``rng.spawn(3)``):
threshold calibration, alternative simulation, and diagnostics. The empirical
placebo method is deterministic (no sampling stream), which is documented as a
limitation: its "sample" is the pre-period placebo windows themselves.

- ``model_simulation`` — model-based counterfactual simulation: fit the test
  region on its controls over the pre-period, fit AR(1) on the residuals, then
  simulate test-window counterfactual totals under the null and under each
  injected effect (aligned with the app's evaluation method);
- ``placebo_empirical`` — empirical placebo-window power: use pre-period
  placebo-window measured uplift-% as the null and apply the legacy closed-form
  shift (the method behind ``compute_power_curve``) — NOT treated as approved
  without explicit review; empty placebo evidence is never padded and is
  enforced by the service (minimum placebo windows);
- ``residual_simulation`` — historical residual simulation: bootstrap the
  pre-period residuals to build the null total distribution.

All fits use the date-keyed alignment in ``geotestlab.power.alignment`` so
missing, duplicated or shuffled dates are reported rather than silently
misaligning controls.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from geotestlab.power.alignment import build_date_keyed_matrix

# Counterfactual fit methods compared for PA-FR2 evidence (see fit_comparison).
FIT_METHOD_NAMES = ("ols", "elastic_net", "lasso")
FALLBACK_FIT_METHOD = "constant_mean"
DEFAULT_MAX_CONDITION_NUMBER = 1e10


# ---------------------------------------------------------------------------
# Estimation helpers
# ---------------------------------------------------------------------------
@dataclass
class CounterfactualFit:
    """Fitted counterfactual model plus structured fit/matrix diagnostics.

    ``cf_fit`` and ``residuals`` are aligned to the RETAINED pre-period rows
    (the rows where the test series and every control were finite);
    ``retained_dates`` records those dates. ``coef`` is the OLS/constant-mean
    coefficient vector (None for sklearn-based fits); ``model`` is the fitted
    sklearn estimator for Elastic Net / LASSO (never serialised).
    ``project(X_const, X_no_const)`` returns the counterfactual for a new
    aligned design.
    """

    coef: np.ndarray | None
    cf_fit: np.ndarray
    residuals: np.ndarray
    fit_method: str
    fit_status: str
    diagnostics: dict
    warnings: tuple
    retained_dates: pd.DatetimeIndex
    cf_mean: float = 0.0
    model: object | None = None

    def project(self, X_const, X_no_const):
        if self.fit_method == FALLBACK_FIT_METHOD:
            return np.full(X_const.shape[0], self.cf_mean)
        if self.model is not None:
            return np.asarray(self.model.predict(X_no_const), dtype=float)
        return X_const @ self.coef


def _design_from_aligned(test, controls):
    """Return ``(X_const, X_no_const, y, retained_dates)`` for the pairwise-
    complete rows of an aligned test series and control matrix."""
    frame = pd.DataFrame({"y": test})
    cols = list(controls.columns)
    for c in cols:
        frame[c] = controls[c].to_numpy()
    frame = frame.dropna()
    y = frame["y"].to_numpy()
    X_no_const = frame[cols].to_numpy() if cols else np.empty((len(frame), 0))
    X_const = (
        np.column_stack([np.ones(len(frame)), X_no_const])
        if X_no_const.shape[1]
        else np.ones((len(frame), 1))
    )
    return X_const, X_no_const, y, pd.DatetimeIndex(frame.index)


def _constant_or_duplicate_columns(X):
    n = X.shape[1]
    constant = [int(j) for j in range(n) if np.ptp(X[:, j]) == 0]
    duplicate = []
    for j in range(n):
        for k in range(j + 1, n):
            if np.allclose(X[:, j], X[:, k]):
                duplicate.append((int(j), int(k)))
    return constant, duplicate


def fit_counterfactual(
    pre_df,
    test_regions,
    control_regions,
    fit_method="ols",
    max_condition_number=DEFAULT_MAX_CONDITION_NUMBER,
):
    """Fit the test KPI on its controls over the pre-period (levels) with an
    explicit fit method, explicit region sets, and a date-keyed design.

    Rank deficiency is NOT passed silently to ``lstsq``'s minimum-norm
    solution. The design is checked for observations, predictor count, matrix
    rank, condition number, constant columns and duplicate columns; when the
    design is underdetermined, rank-deficient or ill-conditioned, the
    constant-mean fallback is activated with the reason recorded and a
    structured warning emitted.
    """
    test, controls, align_diag = build_date_keyed_matrix(pre_df, test_regions, control_regions)
    X_const, X_no_const, y, retained_dates = _design_from_aligned(test, controls)

    n_obs = int(X_const.shape[0])
    n_predictors = int(X_const.shape[1])
    rank = int(np.linalg.matrix_rank(X_const)) if n_obs > 0 else 0
    cond = float(np.linalg.cond(X_const)) if n_obs > 0 else float("inf")
    constant_cols, duplicate_pairs = (
        _constant_or_duplicate_columns(X_const) if n_obs > 0 else ([], [])
    )

    diagnostics = {
        "n_observations": n_obs,
        "n_predictors": n_predictors,
        "matrix_rank": rank,
        "condition_number": cond if np.isfinite(cond) else None,
        "constant_predictors": constant_cols,
        "duplicate_predictor_pairs": [list(p) for p in duplicate_pairs],
        "fallback_used": False,
        "fallback_reason": None,
        "fit_method": fit_method,
        **align_diag,
    }

    warnings = []

    fallback_reason = None
    if n_obs == 0:
        fallback_reason = "no_observations"
    elif n_predictors > n_obs:
        fallback_reason = "underdetermined"
    elif rank < n_predictors:
        fallback_reason = "rank_deficient"
    elif not np.isfinite(cond) or cond > max_condition_number:
        fallback_reason = "ill_conditioned"

    if fallback_reason is not None:
        mean = float(np.mean(y)) if len(y) else 0.0
        cf_fit = np.full(n_obs, mean) if n_obs else np.array([])
        diagnostics["fallback_used"] = True
        diagnostics["fallback_reason"] = fallback_reason
        diagnostics["fit_method"] = FALLBACK_FIT_METHOD
        warnings.append(
            f"counterfactual fit fell back to constant mean: {fallback_reason} "
            f"(rank {rank}/{n_predictors}, condition {cond:.2e}, observations {n_obs})"
        )
        return CounterfactualFit(
            coef=np.array([mean] + [0.0] * (n_predictors - 1)),
            cf_fit=cf_fit,
            residuals=(y - mean) if len(y) else np.array([]),
            fit_method=FALLBACK_FIT_METHOD,
            fit_status="fallback_constant_mean",
            diagnostics=diagnostics,
            warnings=tuple(warnings),
            retained_dates=retained_dates,
            cf_mean=mean,
        )

    if fit_method == "ols":
        coef, *_ = np.linalg.lstsq(X_const, y, rcond=None)
        cf_fit = X_const @ coef
        model = None
    elif fit_method in ("elastic_net", "lasso"):
        from sklearn.linear_model import ElasticNet, Lasso  # lazy import

        if X_no_const.shape[1] == 0:
            model = None
            coef = np.array([float(np.mean(y))])
            cf_fit = np.full(n_obs, float(np.mean(y)))
        else:
            if fit_method == "elastic_net":
                model = ElasticNet(alpha=0.1, l1_ratio=0.5, max_iter=10000, random_state=0).fit(
                    X_no_const, y
                )
            else:
                model = Lasso(alpha=0.1, max_iter=10000, random_state=0).fit(X_no_const, y)
            cf_fit = np.asarray(model.predict(X_no_const), dtype=float)
            coef = np.concatenate([[float(model.intercept_)], np.asarray(model.coef_, dtype=float)])
    else:
        raise ValueError(f"Unknown fit method {fit_method!r}; expected one of {FIT_METHOD_NAMES}")

    return CounterfactualFit(
        coef=coef,
        cf_fit=cf_fit,
        residuals=y - cf_fit,
        fit_method=fit_method,
        fit_status="ok",
        diagnostics=diagnostics,
        warnings=tuple(warnings),
        retained_dates=retained_dates,
        model=model,
    )


def fit_ar1(residuals):
    """Cochrane-Orcutt-style AR(1) fit on residuals: returns (rho, sigma)."""
    r = np.asarray(residuals, dtype=float)
    if len(r) < 3:
        return 0.0, float(np.std(r)) if len(r) else 0.0
    rho = float(np.corrcoef(r[:-1], r[1:])[0, 1]) if np.std(r[:-1]) > 0 else 0.0
    rho = float(np.clip(rho, -0.99, 0.99))
    innov = r[1:] - rho * r[:-1]
    sigma = float(np.std(innov, ddof=1)) if len(innov) > 1 else float(np.std(innov))
    return rho, sigma


def _simulate_ar1_paths(rho, sigma, n_periods, n_sim, rng, e_start=0.0):
    out = np.empty((n_sim, n_periods))
    prev = np.full(n_sim, e_start, dtype=float)
    for t in range(n_periods):
        prev = rho * prev + rng.normal(0.0, sigma, size=n_sim)
        out[:, t] = prev
    return out


def project_counterfactual(fit, test_df, test_regions, control_regions):
    """Project a fitted counterfactual over the test window (date-keyed)."""
    test_test, controls_test, _ = build_date_keyed_matrix(test_df, test_regions, control_regions)
    X_const, X_no_const, _, _ = _design_from_aligned(test_test, controls_test)
    return fit.project(X_const, X_no_const)


def _shift(null, cf_test_sum, effect, injection, n_test, side):
    """Alternative totals = null totals shifted by the effect.

    The effect magnitude is always non-negative; the direction is controlled by
    ``side`` (``one_sided_negative`` injects a negative shift from the positive
    magnitude). Absolute effects shift every test period by a constant; relative
    effects scale the counterfactual total by ``effect/100``. Non-positive null
    totals under a relative effect are marked NaN (low-volume guard) and counted
    as failures.
    """
    direction = -1.0 if side == "one_sided_negative" else 1.0
    if injection == "absolute":
        return null + direction * effect * n_test, 0
    shift = direction * cf_test_sum * (effect / 100.0)
    alt = null + shift
    bad = null <= 0
    alt = np.where(bad, np.nan, alt)
    return alt, int(np.sum(bad))


# ---------------------------------------------------------------------------
# 1. Model-based counterfactual simulation
# ---------------------------------------------------------------------------
def model_simulation(
    pre_df, test_df, test_regions, control_regions, n_test, n_sim, rng, fit_method="ols"
):
    """Model-based counterfactual simulation with independent streams.

    Threshold calibration, alternative simulation and diagnostics each use an
    independent random stream derived from ``rng`` (``rng.spawn(3)``).
    """
    fit = fit_counterfactual(pre_df, test_regions, control_regions, fit_method=fit_method)
    rho, sigma = fit_ar1(fit.residuals)
    e_start = float(fit.residuals[-1]) if len(fit.residuals) else 0.0

    test_test, _, _ = build_date_keyed_matrix(test_df, test_regions, control_regions)
    n_test_use = int(test_test.notna().sum()) if int(test_test.notna().sum()) > 0 else int(n_test)
    cf_test = project_counterfactual(fit, test_df, test_regions, control_regions)
    cf_test_sum = float(np.sum(cf_test))

    cal_rng, alt_rng, diag_rng = rng.spawn(3)

    # 1) threshold-calibration stream
    cal_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, cal_rng, e_start=e_start)
    cal_null = cf_test_sum + cal_paths.sum(axis=1)

    # 2) diagnostics stream (null mean/sd reported separately)
    diag_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, diag_rng, e_start=e_start)
    diag_null = cf_test_sum + diag_paths.sum(axis=1)

    # 3) independent alternative stream (fresh paths per effect call)
    def alt_fn(effect, injection, side):
        alt_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, alt_rng, e_start=e_start)
        alt_null = cf_test_sum + alt_paths.sum(axis=1)
        return _shift(alt_null, cf_test_sum, effect, injection, n_test_use, side)

    meta = {
        "windows_available": int(len(fit.residuals)),
        "windows_used": int(len(fit.residuals)),
        "rho_estimate": rho,
        "sigma_estimate": sigma,
        "null_mean": float(np.nanmean(diag_null)),
        "null_sd": float(np.nanstd(diag_null)),
        "fit_method": fit.fit_method,
        "fit_status": fit.fit_status,
        "matrix_diagnostics": fit.diagnostics,
        "calibration_simulations": int(n_sim),
        "detection_simulations": int(n_sim),
        "failures": 0,
        "warnings": list(fit.warnings),
    }
    return cal_null, alt_fn, meta


# ---------------------------------------------------------------------------
# 2. Placebo-window empirical method
# ---------------------------------------------------------------------------
def build_placebo_windows(pre_df, test_regions, control_regions, window_len):
    """Non-overlapping placebo windows in the pre-period (date-keyed alignment).

    Returns the measured placebo uplift-% per window (window actual total minus
    fitted counterfactual total, relative to the fitted total). An empty result
    is returned as an empty array — the caller must enforce a minimum; empty
    evidence is never padded.
    """
    test, controls, _ = build_date_keyed_matrix(pre_df, test_regions, control_regions)
    fit = fit_counterfactual(pre_df, test_regions, control_regions)
    _, _, y, _ = _design_from_aligned(test, controls)
    cf_fit = fit.cf_fit
    n = len(y)
    pcts = []
    for start in range(0, n - window_len + 1, window_len):
        denom = float(np.sum(cf_fit[start : start + window_len]))
        if denom != 0 and np.isfinite(denom):
            pcts.append(float((np.sum(y[start : start + window_len]) - denom) / denom * 100.0))
    return np.array(pcts, dtype=float)


def placebo_empirical(pre_df, test_df, test_regions, control_regions, n_test, n_sim, rng):
    """Placebo uplift-% null; alt = legacy closed-form shift (relative only).

    Deterministic: there is no Monte-Carlo sampling stream, so the
    threshold-calibration and alternative "samples" are the same pre-period
    placebo windows. This is a documented limitation of the empirical method
    (no independent calibration stream is possible without resampling). Empty
    placebo evidence is NOT replaced with ``[0.0]``; the service enforces
    ``min_placebo_windows`` and returns an explicit incomplete result.
    """
    pcts = build_placebo_windows(pre_df, test_regions, control_regions, n_test)
    null = pcts

    def alt_fn(effect, injection, side):
        if injection == "absolute":
            raise NotImplementedError(
                "placebo_empirical supports relative injection only (documented limitation)"
            )
        return pcts * (1.0 + effect / 100.0) + effect, 0

    meta = {
        "windows_available": int(len(pcts)),
        "windows_used": int(len(pcts)),
        "null_mean": float(np.mean(pcts)) if len(pcts) else float("nan"),
        "null_sd": float(np.std(pcts)) if len(pcts) else float("nan"),
        "fit_method": "n/a",
        "fit_status": "n/a",
        "matrix_diagnostics": {},
        "calibration_simulations": 0,
        "detection_simulations": 0,
        "failures": 0,
        "warnings": [],
    }
    return null, alt_fn, meta


# ---------------------------------------------------------------------------
# 3. Historical residual simulation (bootstrap)
# ---------------------------------------------------------------------------
def residual_simulation(
    pre_df, test_df, test_regions, control_regions, n_test, n_sim, rng, fit_method="ols"
):
    """Null totals by resampling pre-period residuals (with replacement).

    Uses independent calibration / alternative / diagnostics bootstrap streams.
    Empty residual evidence is NOT padded; the service enforces the minimum
    window count and returns an explicit incomplete result.
    """
    fit = fit_counterfactual(pre_df, test_regions, control_regions, fit_method=fit_method)
    resid = fit.residuals
    cf_test = project_counterfactual(fit, test_df, test_regions, control_regions)
    cf_test_sum = float(np.sum(cf_test))

    cal_rng, alt_rng, diag_rng = rng.spawn(3)

    def _bootstrap(stream):
        if len(resid) == 0:
            return np.zeros(n_sim)
        return cf_test_sum + stream.choice(resid, size=(n_sim, n_test), replace=True).sum(axis=1)

    cal_null = _bootstrap(cal_rng)
    diag_null = _bootstrap(diag_rng)

    def alt_fn(effect, injection, side):
        alt_null = _bootstrap(alt_rng)
        return _shift(alt_null, cf_test_sum, effect, injection, n_test, side)

    meta = {
        "windows_available": int(len(resid)),
        "windows_used": int(len(resid)),
        "null_mean": float(np.nanmean(diag_null)),
        "null_sd": float(np.nanstd(diag_null)),
        "fit_method": fit.fit_method,
        "fit_status": fit.fit_status,
        "matrix_diagnostics": fit.diagnostics,
        "calibration_simulations": int(n_sim),
        "detection_simulations": int(n_sim),
        "failures": 0,
        "warnings": list(fit.warnings),
    }
    return cal_null, alt_fn, meta


METHODS = {
    "model_simulation": model_simulation,
    "placebo_empirical": placebo_empirical,
    "residual_simulation": residual_simulation,
}
