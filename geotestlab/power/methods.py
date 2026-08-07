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

Monte-Carlo methods use three independent random streams derived from a
single seed via ``SeedSequence.spawn`` (see ``geotestlab.power.random``):
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
from geotestlab.power.random import child_rngs
from geotestlab.power.safety import (
    BLOCKED as SAFETY_BLOCKED,
)
from geotestlab.power.safety import (
    DEFAULT_SAFETY_POLICY,
    evaluate_safety,
)

# Only BLOCKED refuses a completed result. UNSUPPORTED is deliberately NOT
# treated as blocking here: in this policy it only arises from defensive/
# unreachable branches (e.g. an already-validated frequency), and conflating
# it with BLOCKED would also block the long-accepted constant-mean-fallback
# degraded mode, which control_matrix_support reports as
# SUPPORTED_WITH_WARNING, not BLOCKED.
_SAFETY_BLOCKING_STATUSES = (SAFETY_BLOCKED,)

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
    # The control regions actually used by this fit AFTER sanitisation
    # (constant/exact-duplicate columns removed). project_counterfactual()
    # MUST build the test-window design from this set, not the originally
    # requested control_regions, or the projection's column meanings would
    # no longer match the fitted coefficients/model.
    retained_control_regions: tuple = ()
    # StandardScaler fit on the training controls when fit_method is
    # elastic_net/lasso (matches geotestlab.validation's scaling policy);
    # None for OLS/constant-mean, which are never scaled.
    scaler: object | None = None

    def project(self, X_const, X_no_const):
        if self.fit_method == FALLBACK_FIT_METHOD:
            return np.full(X_const.shape[0], self.cf_mean)
        if self.model is not None:
            X_for_model = (
                self.scaler.transform(X_no_const) if self.scaler is not None else X_no_const
            )
            return np.asarray(self.model.predict(X_for_model), dtype=float)
        return X_const @ self.coef


def _design_from_aligned(test, controls):
    """Return ``(X_const, X_no_const, y, retained_dates, removal_diag)`` for
    the pairwise-complete rows of an aligned test series and control matrix.

    ``retained_dates`` is the single authoritative "jointly complete" date
    set (test AND every control present) for this window -- the same set
    that must drive the counterfactual projection, the simulated-noise
    horizon and the reported effective duration, so they cannot silently
    diverge. ``removal_diag`` records why every non-retained expected date
    was dropped, so the removed set is auditable rather than absorbed into a
    bare row count.
    """
    frame = pd.DataFrame({"y": test})
    cols = list(controls.columns)
    for c in cols:
        frame[c] = controls[c].to_numpy()
    complete = frame.notna().all(axis=1)
    reasons = {}
    for date, row in frame[~complete].iterrows():
        if pd.isna(row["y"]):
            reasons[str(pd.Timestamp(date).date())] = "test_missing"
        else:
            missing_controls = [c for c in cols if pd.isna(row[c])]
            reasons[str(pd.Timestamp(date).date())] = "control_missing:" + ",".join(
                missing_controls
            )
    kept = frame[complete]
    y = kept["y"].to_numpy()
    X_no_const = kept[cols].to_numpy() if cols else np.empty((len(kept), 0))
    X_const = (
        np.column_stack([np.ones(len(kept)), X_no_const])
        if X_no_const.shape[1]
        else np.ones((len(kept), 1))
    )
    removal_diag = {
        "dates_jointly_complete": int(len(kept)),
        "dates_removed_joint": int(len(frame) - len(kept)),
        "removal_reasons": reasons,
    }
    return X_const, X_no_const, y, pd.DatetimeIndex(kept.index), removal_diag


def _constant_or_duplicate_columns(X):
    n = X.shape[1]
    constant = [int(j) for j in range(n) if np.ptp(X[:, j]) == 0]
    duplicate = []
    for j in range(n):
        for k in range(j + 1, n):
            if np.allclose(X[:, j], X[:, k]):
                duplicate.append((int(j), int(k)))
    return constant, duplicate


def _sanitize_controls(X_no_const, cols):
    """Remove constant and exact-duplicate control columns BEFORE rank/
    condition assessment, so one uninformative or duplicated control never
    triggers a full constant-mean fallback that throws away every other,
    still-informative control.

    Returns ``(X_sanitized, cols_sanitized, removed)`` where ``removed`` is a
    JSON-safe list of ``{"region": ..., "reason": ...}`` records ("constant"
    or "duplicate_of:<region>"). Column order among retained controls is
    preserved.
    """
    if X_no_const.shape[1] == 0 or X_no_const.shape[0] == 0:
        return X_no_const, list(cols), []
    constant_mask = np.ptp(X_no_const, axis=0) == 0
    keep_idx = []
    removed = []
    for j, name in enumerate(cols):
        if constant_mask[j]:
            removed.append({"region": name, "reason": "constant"})
            continue
        dup_of = next(
            (cols[k] for k in keep_idx if np.allclose(X_no_const[:, j], X_no_const[:, k])),
            None,
        )
        if dup_of is not None:
            removed.append({"region": name, "reason": f"duplicate_of:{dup_of}"})
            continue
        keep_idx.append(j)
    X_sanitized = X_no_const[:, keep_idx]
    cols_sanitized = [cols[j] for j in keep_idx]
    return X_sanitized, cols_sanitized, removed


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
    X_const_raw, X_no_const_raw, y, retained_dates, removal_diag = _design_from_aligned(
        test, controls
    )
    cols = list(controls.columns)

    # Sanitise BEFORE rank/condition assessment: an exact-duplicate or
    # constant control must not throw away every other, still-informative
    # control via a full fallback. Removed columns are recorded; the
    # projection MUST later use the same sanitised control set (see
    # CounterfactualFit.retained_control_regions / project_counterfactual()).
    X_no_const, cols_sanitized, removed_controls = _sanitize_controls(X_no_const_raw, cols)
    n_obs = int(X_const_raw.shape[0])
    X_const = (
        np.column_stack([np.ones(n_obs), X_no_const])
        if X_no_const.shape[1]
        else np.ones((n_obs, 1))
    )

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
        "removed_controls": removed_controls,
        "retained_control_regions": list(cols_sanitized),
        "fallback_used": False,
        "fallback_reason": None,
        "fit_method": fit_method,
        **align_diag,
        **removal_diag,
    }

    warnings = []
    if removed_controls:
        warnings.append(
            "sanitised "
            + ", ".join(f"{r['region']} ({r['reason']})" for r in removed_controls)
            + " before fitting; remaining informative controls preserved"
        )

    fallback_reason = None
    if n_obs == 0:
        fallback_reason = "no_observations"
    elif cols and not cols_sanitized:
        fallback_reason = "no_informative_controls_after_sanitisation"
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
        diagnostics["cv_status"] = "not applicable: constant-mean fallback"
        diagnostics["used_cv"] = False
        diagnostics["selected_alpha"] = None
        diagnostics["selected_l1_ratio"] = None
        diagnostics["cv_folds"] = None
        diagnostics["training_periods"] = n_obs
        diagnostics["evaluation_alignment"] = (
            "constant-mean fallback -- approximates no regression-based evaluation "
            "method; credible control information was not available for this design "
            "(see fallback_reason)."
        )
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
            retained_control_regions=(),
        )

    scaler = None
    if fit_method == "ols":
        coef, *_ = np.linalg.lstsq(X_const, y, rcond=None)
        cf_fit = X_const @ coef
        model = None
        diagnostics["cv_status"] = "not applicable: OLS is an unregularised baseline fit"
        diagnostics["used_cv"] = False
        diagnostics["selected_alpha"] = None
        diagnostics["selected_l1_ratio"] = None
        diagnostics["cv_folds"] = None
        diagnostics["training_periods"] = n_obs
        diagnostics["evaluation_alignment"] = (
            "baseline OLS -- NOT the production evaluation fitting policy. The app's "
            "Validate Test Design / Measure Test Impact evaluation "
            "(geotestlab.validation.service) always fits a TimeSeriesSplit-CV-selected "
            "or exploratory-fallback Elastic Net/LASSO on standardised controls, never "
            "unregularised OLS."
        )
    elif fit_method in ("elastic_net", "lasso"):
        from sklearn.preprocessing import StandardScaler  # lazy import

        from geotestlab.validation.regularisation import build_regularized_model

        if X_no_const.shape[1] == 0:
            model = None
            coef = np.array([float(np.mean(y))])
            cf_fit = np.full(n_obs, float(np.mean(y)))
            diagnostics["cv_status"] = "not applicable: no informative controls to regularise"
            diagnostics["used_cv"] = False
            diagnostics["selected_alpha"] = None
            diagnostics["selected_l1_ratio"] = None
            diagnostics["cv_folds"] = None
        else:
            # Matches geotestlab.validation's fitting policy exactly: the same
            # build_regularized_model() (TimeSeriesSplit-CV ElasticNetCV when
            # there is enough pre-period history, else an exploratory
            # fixed-alpha ElasticNet explicitly labelled as such) on
            # StandardScaler-scaled controls, never a silently fixed alpha.
            method_key = "enet" if fit_method == "elastic_net" else "lasso"
            model, cv_status, used_cv = build_regularized_model(method_key, n_obs)
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_no_const)
            model.fit(X_scaled, y)
            cf_fit = np.asarray(model.predict(X_scaled), dtype=float)
            coef = np.concatenate([[float(model.intercept_)], np.asarray(model.coef_, dtype=float)])
            diagnostics["cv_status"] = cv_status
            diagnostics["used_cv"] = bool(used_cv)
            diagnostics["selected_alpha"] = float(model.alpha_) if used_cv else float(model.alpha)
            diagnostics["selected_l1_ratio"] = (
                float(model.l1_ratio_) if used_cv else float(model.l1_ratio)
            )
            diagnostics["cv_folds"] = int(model.cv.n_splits) if used_cv else None
        diagnostics["training_periods"] = n_obs
        diagnostics["evaluation_alignment"] = (
            "matches the production evaluation fitting policy "
            "(geotestlab.validation.regularisation.build_regularized_model): "
            "TimeSeriesSplit-CV-selected regularisation when history is sufficient, "
            "otherwise the SAME exploratory fixed-alpha fallback the app itself labels "
            "as not cross-validated."
            if diagnostics["used_cv"]
            else "exploratory fixed-alpha fallback (insufficient history for "
            "TimeSeriesSplit CV) -- NOT cross-validated, matching "
            "geotestlab.validation's own exploratory-fallback labelling; excluded from "
            "any comparison that assumes a cross-validated fit."
        )
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
        retained_control_regions=tuple(cols_sanitized),
        scaler=scaler,
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


def _safety_diagnostics(fit, frequency, policy=DEFAULT_SAFETY_POLICY):
    """Evaluate the methodology safety policy against a pre-period fit.

    Computed once per fit (regardless of which simulation method is used
    downstream) so persistence/heteroskedasticity/history checks are
    consistent across model_simulation, residual_simulation and
    placebo_empirical -- they are properties of the retained pre-period
    data and the fit, not of the simulation approach.
    """
    rho, _sigma = fit_ar1(fit.residuals)
    retained_periods = int(fit.diagnostics.get("dates_jointly_complete", len(fit.residuals)))
    continuity = str(fit.diagnostics.get("continuity", "unknown"))
    n_predictors = int(fit.diagnostics.get("n_predictors", 0))
    return evaluate_safety(
        frequency=frequency,
        retained_periods=retained_periods,
        continuity=continuity,
        n_predictors=n_predictors,
        rho=rho,
        fit_diagnostics=fit.diagnostics,
        residuals=fit.residuals,
        level=fit.cf_fit,
        policy=policy,
    )


def _simulate_ar1_paths(rho, sigma, n_periods, n_sim, rng, e_start=0.0):
    out = np.empty((n_sim, n_periods))
    prev = np.full(n_sim, e_start, dtype=float)
    for t in range(n_periods):
        prev = rho * prev + rng.normal(0.0, sigma, size=n_sim)
        out[:, t] = prev
    return out


def project_counterfactual(fit, test_df, test_regions, control_regions):
    """Project a fitted counterfactual over the test window (date-keyed).

    Uses ``fit.retained_control_regions`` (the SANITISED control set the fit
    was actually trained on), not the raw ``control_regions`` argument -- a
    control dropped as constant/exact-duplicate before fitting must also be
    dropped from the test-window design, or the projected columns would no
    longer match the fitted coefficients/model.

    Returns ``(projected, retained_dates, window_diag)``. ``retained_dates``
    is the jointly-complete test-window date set (test AND every retained
    control present that date) -- the single authoritative set that
    ``model_simulation``/``residual_simulation`` must also use for the
    simulated-noise horizon, so the counterfactual projection and the noise
    horizon can never silently diverge. ``window_diag`` merges the alignment
    diagnostics (including ``duplicate_keys_blocking``) with the joint-row
    removal diagnostics for this window.
    """
    used_controls = fit.retained_control_regions
    test_test, controls_test, align_diag = build_date_keyed_matrix(
        test_df, test_regions, used_controls
    )
    X_const, X_no_const, _, retained_dates, removal_diag = _design_from_aligned(
        test_test, controls_test
    )
    projected = fit.project(X_const, X_no_const)
    window_diag = {**align_diag, **removal_diag}
    return projected, retained_dates, window_diag


def _shift(null, cf_test_sum, effect, injection, n_test, side):
    """Alternative totals = null totals shifted by the effect.

    The effect magnitude is always non-negative; the direction is controlled by
    ``side`` (``one_sided_negative`` injects a negative shift from the positive
    magnitude). Absolute effects shift every test period by a constant; relative
    effects scale the FIXED counterfactual baseline (``cf_test_sum``) by
    ``effect/100`` and add that constant shift to every simulated draw -- the
    shift depends only on the fixed baseline, never on the realised value of
    an individual draw. Callers must validate the baseline BEFORE calling this
    (a non-positive ``cf_test_sum`` makes a relative effect undefined and must
    block relative injection or require absolute injection at the caller,
    not censor individual draws by their own simulated sign here).
    """
    null = np.asarray(null, dtype=float)
    direction = -1.0 if side == "one_sided_negative" else 1.0
    if injection == "absolute":
        return null + direction * effect * n_test, 0
    shift = direction * cf_test_sum * (effect / 100.0)
    return null + shift, 0


def _blocked_result(reason, matrix_diagnostics=None, fit_method="n/a", fit_status="blocked"):
    """A method result that refuses to produce a completed power estimate.

    Used when the aligned window cannot support analysis at all (duplicate
    selected-region keys, or zero jointly-complete test-window dates) --
    letting arbitrary row order or a silent fallback horizon decide the
    answer is unacceptable, so the service must surface this as a blocker.
    """

    def alt_fn(effect, injection, side):
        return np.array([], dtype=float), 0

    meta = {
        "windows_available": 0,
        "windows_used": 0,
        "null_mean": float("nan"),
        "null_sd": float("nan"),
        "fit_method": fit_method,
        "fit_status": fit_status,
        "matrix_diagnostics": matrix_diagnostics or {},
        "calibration_simulations": 0,
        "detection_simulations": 0,
        "failures": 0,
        "warnings": [],
        "blocked": True,
        "block_reason": reason,
    }
    return np.array([], dtype=float), alt_fn, meta


# ---------------------------------------------------------------------------
# 1. Model-based counterfactual simulation
# ---------------------------------------------------------------------------
def model_simulation(
    pre_df,
    test_df,
    test_regions,
    control_regions,
    n_test,
    n_sim,
    seed,
    fit_method="ols",
    frequency="weekly",
    safety_policy=DEFAULT_SAFETY_POLICY,
    enforce_safety=True,
):
    """Model-based counterfactual simulation with independent streams.

    Threshold calibration, alternative simulation and diagnostics each use an
    independent random stream derived from ``seed`` (``child_rngs(seed, 3)``),
    which is NumPy >= 1.24 compatible.

    ``enforce_safety=False`` skips the methodology safety policy (still
    computed as ``None`` in ``meta["safety"]``) -- used by
    ``fit_comparison.compare_fit_methods``, a fit-method EVIDENCE pathway
    that deliberately exercises short-history/rank-deficient scenarios and
    does not go through ``run_power_analysis``'s safety-gated contract.
    """
    fit = fit_counterfactual(pre_df, test_regions, control_regions, fit_method=fit_method)
    if fit.diagnostics.get("duplicate_keys_blocking"):
        return _blocked_result(
            "duplicate (region, date) keys among selected regions in the pre-period; "
            "refusing to resolve by row order",
            matrix_diagnostics=fit.diagnostics,
            fit_method=fit.fit_method,
        )
    safety = _safety_diagnostics(fit, frequency, safety_policy) if enforce_safety else None
    if safety is not None and safety["overall_status"] in _SAFETY_BLOCKING_STATUSES:
        return _blocked_result(
            "; ".join(safety["reasons"]) or "methodology safety policy blocked this analysis",
            matrix_diagnostics={**fit.diagnostics, "safety": safety},
            fit_method=fit.fit_method,
        )
    rho, sigma = fit_ar1(fit.residuals)
    e_start = float(fit.residuals[-1]) if len(fit.residuals) else 0.0

    cf_test, retained_test_dates, test_align_diag = project_counterfactual(
        fit, test_df, test_regions, control_regions
    )
    matrix_diagnostics = {**fit.diagnostics, "safety": safety, "test_window": test_align_diag}
    if test_align_diag.get("duplicate_keys_blocking"):
        return _blocked_result(
            "duplicate (region, date) keys among selected regions in the test window; "
            "refusing to resolve by row order",
            matrix_diagnostics=matrix_diagnostics,
            fit_method=fit.fit_method,
        )
    n_test_use = int(len(retained_test_dates))
    cf_test_sum = float(np.sum(cf_test))
    if n_test_use == 0:
        return _blocked_result(
            "no jointly complete test-window dates (test and every control present) "
            "available to project the counterfactual or simulate a horizon",
            matrix_diagnostics=matrix_diagnostics,
            fit_method=fit.fit_method,
        )

    cal_rng, alt_rng, diag_rng = child_rngs(seed, 3)

    # 1) threshold-calibration stream
    cal_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, cal_rng, e_start=e_start)
    cal_null = cf_test_sum + cal_paths.sum(axis=1)

    # 2) diagnostics stream (null mean/sd reported separately)
    diag_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, diag_rng, e_start=e_start)
    diag_null = cf_test_sum + diag_paths.sum(axis=1)

    # 3) independent alternative stream: ONE no-effect draw per run (common
    # random numbers), reused across every requested effect magnitude via a
    # deterministic shift. Adding/reordering effect-grid points can no longer
    # change the underlying noise a given effect is evaluated against.
    alt_paths = _simulate_ar1_paths(rho, sigma, n_test_use, n_sim, alt_rng, e_start=e_start)
    alt_null_fixed = cf_test_sum + alt_paths.sum(axis=1)

    def alt_fn(effect, injection, side):
        return _shift(alt_null_fixed, cf_test_sum, effect, injection, n_test_use, side)

    meta = {
        "windows_available": int(len(fit.residuals)),
        "windows_used": int(len(fit.residuals)),
        "rho_estimate": rho,
        "sigma_estimate": sigma,
        "null_mean": float(np.nanmean(diag_null)),
        "null_sd": float(np.nanstd(diag_null)),
        "fit_method": fit.fit_method,
        "fit_status": fit.fit_status,
        "matrix_diagnostics": matrix_diagnostics,
        "calibration_simulations": int(n_sim),
        "detection_simulations": int(n_sim),
        "failures": 0,
        "warnings": list(fit.warnings),
        "effective_test_periods": n_test_use,
        "requested_test_periods": int(n_test),
        "cf_test_sum": cf_test_sum,
        "safety": safety,
        "blocked": False,
        "block_reason": None,
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
    _, _, y, _, _ = _design_from_aligned(test, controls)
    cf_fit = fit.cf_fit
    n = len(y)
    pcts = []
    for start in range(0, n - window_len + 1, window_len):
        denom = float(np.sum(cf_fit[start : start + window_len]))
        if denom != 0 and np.isfinite(denom):
            pcts.append(float((np.sum(y[start : start + window_len]) - denom) / denom * 100.0))
    return np.array(pcts, dtype=float)


def placebo_empirical(
    pre_df,
    test_df,
    test_regions,
    control_regions,
    n_test,
    n_sim,
    seed,
    frequency="weekly",
    safety_policy=DEFAULT_SAFETY_POLICY,
    enforce_safety=True,
):
    """Placebo uplift-% null; alt = legacy closed-form shift (relative only).

    Deterministic: there is no Monte-Carlo sampling stream, so the
    threshold-calibration and alternative "samples" are the same pre-period
    placebo windows. This is a documented limitation of the empirical method
    (no independent calibration stream is possible without resampling). Empty
    placebo evidence is NOT replaced with ``[0.0]``; the service enforces
    ``min_placebo_windows`` and returns an explicit incomplete result.

    The non-negative magnitude convention is applied consistently: the effect
    magnitude is always non-negative and the direction is controlled by
    ``side`` (``one_sided_positive`` shifts up, ``one_sided_negative`` shifts
    down, ``two_sided`` uses the documented default signed shift — positive —
    with two-tailed detection). ``seed`` is unused (the method is
    deterministic) and is kept only to share the method-dispatch signature.
    """
    pre_fit = fit_counterfactual(pre_df, test_regions, control_regions)
    if pre_fit.diagnostics.get("duplicate_keys_blocking"):
        return _blocked_result(
            "duplicate (region, date) keys among selected regions in the pre-period; "
            "refusing to resolve by row order",
            matrix_diagnostics=pre_fit.diagnostics,
            fit_method="n/a",
        )
    safety = _safety_diagnostics(pre_fit, frequency, safety_policy) if enforce_safety else None
    if safety is not None and safety["overall_status"] in _SAFETY_BLOCKING_STATUSES:
        return _blocked_result(
            "; ".join(safety["reasons"]) or "methodology safety policy blocked this analysis",
            matrix_diagnostics={**pre_fit.diagnostics, "safety": safety},
            fit_method="n/a",
        )
    pcts = build_placebo_windows(pre_df, test_regions, control_regions, n_test)
    null = pcts

    def alt_fn(effect, injection, side):
        if injection == "absolute":
            raise NotImplementedError(
                "placebo_empirical supports relative injection only (documented limitation)"
            )
        direction = -1.0 if side == "one_sided_negative" else 1.0
        signed = direction * effect
        return pcts * (1.0 + signed / 100.0) + signed, 0

    meta = {
        "windows_available": int(len(pcts)),
        "windows_used": int(len(pcts)),
        "null_mean": float(np.mean(pcts)) if len(pcts) else float("nan"),
        "null_sd": float(np.std(pcts)) if len(pcts) else float("nan"),
        "fit_method": "n/a",
        "fit_status": "n/a",
        "matrix_diagnostics": {"safety": safety},
        "calibration_simulations": 0,
        "detection_simulations": 0,
        "failures": 0,
        "warnings": [],
        "safety": safety,
        "blocked": False,
        "block_reason": None,
    }
    return null, alt_fn, meta


# ---------------------------------------------------------------------------
# 3. Historical residual simulation (bootstrap)
# ---------------------------------------------------------------------------
def residual_simulation(
    pre_df,
    test_df,
    test_regions,
    control_regions,
    n_test,
    n_sim,
    seed,
    fit_method="ols",
    frequency="weekly",
    safety_policy=DEFAULT_SAFETY_POLICY,
    enforce_safety=True,
):
    """Null totals by resampling pre-period residuals (with replacement).

    Uses independent calibration / alternative / diagnostics bootstrap streams
    derived from ``seed`` (``child_rngs(seed, 3)``, NumPy >= 1.24 compatible).
    Empty residual evidence is NOT padded; the service enforces the minimum
    window count and returns an explicit incomplete result.
    """
    fit = fit_counterfactual(pre_df, test_regions, control_regions, fit_method=fit_method)
    if fit.diagnostics.get("duplicate_keys_blocking"):
        return _blocked_result(
            "duplicate (region, date) keys among selected regions in the pre-period; "
            "refusing to resolve by row order",
            matrix_diagnostics=fit.diagnostics,
            fit_method=fit.fit_method,
        )
    safety = _safety_diagnostics(fit, frequency, safety_policy) if enforce_safety else None
    if safety is not None and safety["overall_status"] in _SAFETY_BLOCKING_STATUSES:
        return _blocked_result(
            "; ".join(safety["reasons"]) or "methodology safety policy blocked this analysis",
            matrix_diagnostics={**fit.diagnostics, "safety": safety},
            fit_method=fit.fit_method,
        )
    resid = fit.residuals
    cf_test, retained_test_dates, test_align_diag = project_counterfactual(
        fit, test_df, test_regions, control_regions
    )
    matrix_diagnostics = {**fit.diagnostics, "safety": safety, "test_window": test_align_diag}
    if test_align_diag.get("duplicate_keys_blocking"):
        return _blocked_result(
            "duplicate (region, date) keys among selected regions in the test window; "
            "refusing to resolve by row order",
            matrix_diagnostics=matrix_diagnostics,
            fit_method=fit.fit_method,
        )
    n_test_use = int(len(retained_test_dates))
    cf_test_sum = float(np.sum(cf_test))
    if n_test_use == 0:
        return _blocked_result(
            "no jointly complete test-window dates (test and every control present) "
            "available to project the counterfactual or bootstrap a horizon",
            matrix_diagnostics=matrix_diagnostics,
            fit_method=fit.fit_method,
        )

    cal_rng, alt_rng, diag_rng = child_rngs(seed, 3)

    def _bootstrap(stream):
        if len(resid) == 0:
            return np.zeros(n_sim)
        return cf_test_sum + stream.choice(resid, size=(n_sim, n_test_use), replace=True).sum(
            axis=1
        )

    cal_null = _bootstrap(cal_rng)
    diag_null = _bootstrap(diag_rng)

    # Common random numbers: ONE alternative no-effect bootstrap draw per run,
    # reused across every requested effect magnitude via a deterministic
    # shift (see model_simulation's alt_fn for the same rationale).
    alt_null_fixed = _bootstrap(alt_rng)

    def alt_fn(effect, injection, side):
        return _shift(alt_null_fixed, cf_test_sum, effect, injection, n_test_use, side)

    meta = {
        "windows_available": int(len(resid)),
        "windows_used": int(len(resid)),
        "null_mean": float(np.nanmean(diag_null)),
        "null_sd": float(np.nanstd(diag_null)),
        "fit_method": fit.fit_method,
        "fit_status": fit.fit_status,
        "matrix_diagnostics": matrix_diagnostics,
        "calibration_simulations": int(n_sim),
        "detection_simulations": int(n_sim),
        "failures": 0,
        "warnings": list(fit.warnings),
        "effective_test_periods": n_test_use,
        "requested_test_periods": int(n_test),
        "cf_test_sum": cf_test_sum,
        "safety": safety,
        "blocked": False,
        "block_reason": None,
    }
    return cal_null, alt_fn, meta


METHODS = {
    "model_simulation": model_simulation,
    "placebo_empirical": placebo_empirical,
    "residual_simulation": residual_simulation,
}
