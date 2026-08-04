"""Model feature construction: combined model matrix, lagged controls, period splits."""

from __future__ import annotations

from sklearn.preprocessing import StandardScaler

from geotestlab.bayesian.exceptions import InsufficientPrePeriodError, MissingTestPeriodError
from geotestlab.bayesian.models import BayesianModelData
from geotestlab.validation import add_lagged_control_features, build_model_matrix


def build_bayesian_model_data(
    agg_df,
    control_list,
    test_regions,
    frequency_config,
    include_lagged_controls,
    lag_periods,
    pre_start_ts,
    pre_end_ts,
    test_start_ts,
    test_end_ts,
    use_post,
    post_start_ts,
    post_end_ts,
    min_pre_period_rows=6,
) -> BayesianModelData:
    """Build the combined pre/test(/post) model matrix and period splits.

    A single combined matrix is built across the full continuous date range so
    frequency-aware lagged control features (if enabled) apply once, then the
    matrix is split back out by period. Raises
    :class:`InsufficientPrePeriodError` / :class:`MissingTestPeriodError` when a
    required period is missing.
    """
    # ---- Build a combined pre + test/post model matrix so frequency-aware lagged
    # control features (if enabled) apply once across the full continuous
    # date range, then split back out by period. ----
    _combined_end_candidates = [pre_end_ts]
    if test_end_ts is not None:
        _combined_end_candidates.append(test_end_ts)
    if use_post and post_end_ts is not None:
        _combined_end_candidates.append(post_end_ts)
    combined_end_ts = max(_combined_end_candidates)

    full_mask = (agg_df["date"] >= pre_start_ts) & (agg_df["date"] <= combined_end_ts)
    model_full_bayes, matrix_diagnostics = build_model_matrix(
        agg_df[full_mask], control_list, test_regions
    )

    if include_lagged_controls:
        (
            model_full_bayes,
            model_feature_cols,
            lagged_feature_map,
            lag_drop_metadata,
        ) = add_lagged_control_features(
            model_full_bayes,
            control_list,
            lags=(lag_periods,),
            frequency_config=frequency_config,
        )
    else:
        model_feature_cols = list(control_list)
        lagged_feature_map = {}
        lag_drop_metadata = None

    # ---- Pre period ----
    pre_mask = (model_full_bayes["date"] >= pre_start_ts) & (model_full_bayes["date"] <= pre_end_ts)
    model_pre = model_full_bayes[pre_mask].sort_values("date").reset_index(drop=True)
    if len(model_pre) < min_pre_period_rows:
        # Copy preserved verbatim from the pre-extraction app message.
        raise InsufficientPrePeriodError("Not enough pre‑period data for Bayesian model.")
    X_pre = model_pre[model_feature_cols].values
    y_pre = model_pre["test_kpi"].values
    pre_dates = model_pre["date"].values
    scaler_X = StandardScaler()
    X_pre_scaled = scaler_X.fit_transform(X_pre)
    scaler_y = StandardScaler()
    y_pre_scaled = scaler_y.fit_transform(y_pre.reshape(-1, 1)).flatten()

    # ---- Test period ----
    test_mask = (model_full_bayes["date"] >= test_start_ts) & (
        model_full_bayes["date"] <= test_end_ts
    )
    model_test = model_full_bayes[test_mask].sort_values("date").reset_index(drop=True)
    if model_test.empty:
        raise MissingTestPeriodError("No test period data available.")
    X_test = model_test[model_feature_cols].values
    X_test_scaled = scaler_X.transform(X_test)
    y_test_actual = model_test["test_kpi"].values
    test_dates = model_test["date"].values

    # ---- Post period (optional) ----
    if use_post and post_start_ts is not None and post_end_ts is not None:
        post_mask = (model_full_bayes["date"] >= post_start_ts) & (
            model_full_bayes["date"] <= post_end_ts
        )
        model_post = model_full_bayes[post_mask].sort_values("date").reset_index(drop=True)
        if not model_post.empty:
            X_post = model_post[model_feature_cols].values
            X_post_scaled = scaler_X.transform(X_post)
            y_post_actual = model_post["test_kpi"].values
            post_dates = model_post["date"].values
        else:
            X_post_scaled = None
            y_post_actual = None
            post_dates = None
    else:
        X_post_scaled = None
        y_post_actual = None
        post_dates = None

    return BayesianModelData(
        model_full_bayes=model_full_bayes,
        feature_cols=tuple(model_feature_cols),
        lagged_feature_map=lagged_feature_map,
        lag_drop_metadata=lag_drop_metadata,
        matrix_diagnostics=matrix_diagnostics,
        X_pre=X_pre_scaled,
        y_pre=y_pre,
        y_pre_scaled=y_pre_scaled,
        pre_dates=pre_dates,
        X_test=X_test_scaled,
        y_test_actual=y_test_actual,
        test_dates=test_dates,
        X_post=X_post_scaled,
        y_post_actual=y_post_actual,
        post_dates=post_dates,
        scaler_X=scaler_X,
        scaler_y=scaler_y,
    )
