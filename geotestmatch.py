import importlib.metadata
import io
import json
import os
import platform
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum

import altair as alt
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from scipy import stats

# Bayesian core (geotestlab.bayesian) — pure functions, no Streamlit imports.
from geotestlab.bayesian import (
    BayesianConfig,
    run_bayesian,
    summarize_mcmc_diagnostics,
)
from geotestlab.data import RegionalKPIConfig, prepare_regional_kpi

# pymc and arviz imported lazily inside the Bayesian tab to avoid
# segfaults and Numba errors at startup on Python 3.14
from geotestlab.data.exceptions import (
    MissingIdentifierColumnsError,
    NoRetainedKPIObservationsError,
    NoValidDateColumnsError,
    UnreadableWorkbookError,
    UnresolvedAggregationColumnError,
    UnresolvedMetricColumnError,
)
from geotestlab.data.ingestion import detect_date_columns, detect_metric_column
from geotestlab.data.ingestion import load_and_reshape_kpi as _load_and_reshape_kpi
from geotestlab.data.mapping import (
    build_region_mapping,
    compute_region_mapping_report,
    region_mapping_fingerprint,
    uncovered_required_regions,
)
from geotestlab.data.models import compute_mapping_report
from geotestlab.data.period_quality import compute_period_quality
from geotestlab.effect.plausibility import effect_input_fingerprint
from geotestlab.effect.ui import render_effect_plausibility_tab

# Experiment record (geotestlab.experiment) — identity, fingerprints, stage
# status, design freeze, and reproducible export. Pure, no Streamlit imports.
from geotestlab.experiment import (
    STAGE_KEYS,
    STAGE_LABELS,
    ExperimentRecord,
    active_frozen_version,
    build_content_digests,
    build_experiment_export,
    build_frozen_data_quality_summary,
    build_frozen_matching_section,
    build_unified_result_summaries,
    candidate_universe_digest,
    compute_input_fingerprint,
    create_experiment_record,
    freeze_design,
    material_file_identity,
    observed_impact_completed,
    planned_vs_analysed,
    propagate_staleness,
    record_stage_method_result,
    record_stage_result,
    sha256_bytes,
    tool_version,
    update_inputs,
    utc_now_iso,
)

# Matching core (geotestlab.matching) — pure functions, no Streamlit imports.
from geotestlab.matching import (
    ADOBE_COL,
    GUIDED_SEARCH_CONFIG,
    POPULATION_COL,
    MatchConstraints,
    basic_strategy,
    build_kpi_pattern_agg_df,
    build_kpi_pattern_wide_from_regional,
    calculate_experiment_population_coverage,
    calculate_metrics,
    calculate_metrics_from_flat,
    find_guided_test_group,
    fit_structural_stats,
    get_grouping_columns,
    get_numeric_metric_columns,
    impute_missing_features,
    index_kpi_series_to_100,
    intermediate_strategy,
    make_fast_metrics_fn,
    nearest_neighbor_start,
    normalise_column_names,
    prepare_market_dataframe,
    retain_kpi_dates,
    stochastic_genetic_search,
    validate_constraints,
)
from geotestlab.matching import (
    aggregate_market_data as _aggregate_market_data,
)
from geotestlab.matching import (
    preprocess_data as _preprocess_data,
)
from geotestlab.matching import (
    read_kpi_pattern_excel as _read_kpi_pattern_excel,
)
from geotestlab.media.delivery import delivery_input_fingerprint
from geotestlab.media.ui import render_media_delivery_tab
from geotestlab.power.production import (
    production_input_fingerprint,
)
from geotestlab.power.ui import render_power_test_sizing_tab
from geotestlab.recommendation.ui import render_design_recommendation_tab

# Validation core (geotestlab.validation) — pure functions, no Streamlit imports.
from geotestlab.validation import (
    RELIABILITY_THRESHOLDS,
    get_frequency_config,
    infer_time_series_frequency,
    rolling_origin_validation,
    run_validation,
)
from geotestlab.validation.metrics import _is_valid_number
from geotestlab.validation.models import ValidationConfig, ValidationPeriods

# ------------------------------------------------------------
# App configuration
# ------------------------------------------------------------

st.set_page_config(page_title="TEST GeoTestLab", layout="wide")


def load_css(path: str = "styles.css") -> None:
    try:
        with open(path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass


load_css()

# ---- Smaller download buttons ----
# Scoped to st.download_button() specifically (not st.button()), so the primary
# action buttons (Run Match Analysis, Export to Excel, etc.) keep their current size
# and only the download buttons (Excel export + the three chart-data downloads) shrink.
# Added here inline rather than relying on styles.css, since that file isn't guaranteed
# to be present in every environment.
st.markdown(
    """
<style>
div[data-testid="stDownloadButton"] button {
    font-size: 0.75rem;
    padding: 0.15rem 0.6rem;
    line-height: 1.3;
}
div[data-testid="stDownloadButton"] button p {
    font-size: 0.75rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.title("TEST GeoTestLab")
st.caption(
    "Build statistically balanced test and control groups for geo-testing — no coding required."
)

# ------------------------------------------------------------
# Configuration constants
# ------------------------------------------------------------

CONFIG = {
    "max_hill_climbing_swaps": 15,
    "genetic_iterations": {"min": 100, "max": 5000, "default": 1000},
    "max_control_pool_size": 50,
    "smd_thresholds": {"good": 0.20, "high": 0.50},
    "cache_ttl": 3600,
    "max_display_features": 10,
    "missing_threshold": 20,  # % missing above which we warn
    "outlier_std_threshold": 5,
    "ess_min_threshold": 500,  # softer threshold for ESS (was 1000)
    # ---- Method comparison / Counterfactual Confidence traffic-light bands ----
    # Single source of truth lives in geotestlab.validation.confidence
    # (RELIABILITY_THRESHOLDS); CONFIG points at it so the app keeps one source.
    "reliability_thresholds": RELIABILITY_THRESHOLDS,
}

# Single source of truth for SMD thresholds: CONFIG["smd_thresholds"] is canonical;
# these module-level names exist for readability at the (many) call sites.
SMD_GOOD_THRESHOLD = CONFIG["smd_thresholds"]["good"]
SMD_HIGH_THRESHOLD = CONFIG["smd_thresholds"]["high"]

DATA_PATH = os.environ.get(
    "GEOTESTLAB_DATA_PATH",
    "data/Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx",
)

# ------------------------------------------------------------
# Time-Series Validation helpers
# ------------------------------------------------------------

METHOD_STRUCTURAL = "Structurally Matched Controls"
METHOD_DATA_OPTIMISED = "Data-Optimised Controls"
METHOD_DATA_OPTIMISED_EXCL = "Data-Optimised Controls (Excluding Force-Exclude Regions)"
METHOD_USER_SELECTED = "User Selected Test and Control"


def load_and_reshape_kpi(uploaded_file, agg_col=None, metric_col=None):
    """Streamlit adapter over geotestlab.data.ingestion.load_and_reshape_kpi.

    Translates the pure module's domain exceptions into this app's existing
    user-facing st.error()/st.stop() behaviour, and returns the typed
    ParsedKPIData so callers retain both the long-format DataFrame and the
    data-quality report.
    """
    try:
        parsed = _load_and_reshape_kpi(uploaded_file, agg_col=agg_col, metric_col=metric_col)
    except UnreadableWorkbookError as e:
        st.error(
            "The KPI file could not be read with either the calamine or openpyxl engine. "
            "Please confirm this is a valid .xlsx file and try again. "
            f"(Details: {e})"
        )
        st.stop()
    except MissingIdentifierColumnsError:
        st.error(
            "This file doesn't have enough columns to identify a region and a metric. "
            "Expected at least a region column and a metric column."
        )
        st.stop()
    except (UnresolvedAggregationColumnError, UnresolvedMetricColumnError) as e:
        raise ValueError(str(e)) from e
    except NoValidDateColumnsError:
        st.error(
            "No date columns were found in this file. Date columns must use Excel "
            "date-formatted headers."
        )
        st.stop()
    except NoRetainedKPIObservationsError:
        st.error(
            "No KPI observations remain after removing invalid dates and missing/"
            "non-numeric KPI values. Please check the uploaded file."
        )
        st.stop()
    return parsed


def _quality_blocking_errors():
    """Collect blocking errors from the stored parse and region-mapping reports.

    The app refuses to run validation/evaluation/KPI-pattern/Bayesian modelling
    while any blocker is present — warnings never block; only explicit
    blocking errors do.

    Region-mapping blockers cover a required selected test region that the
    mapped KPI data does not cover (absent from the file, or its raw label
    could not be resolved). Unused unmapped raw regions are warnings, never
    blockers.
    """
    errors: list[str] = []
    report = st.session_state.get("kpi_quality_report")
    if report is not None:
        errors.extend(report.blocking_errors)
    mapping = st.session_state.get("kpi_mapping_report")
    if mapping is not None:
        required = st.session_state.get("selected_experiment_regions", []) or []
        uncovered = uncovered_required_regions(mapping, required)
        if uncovered:
            errors.append(
                "The following selected test region(s) have no mapped data in the KPI file: "
                + ", ".join(uncovered)
            )
    return errors


def render_kpi_quality_report(report, rejected_rows=None, mapping_report=None):
    """Render the parse-time data-quality report.

    Distinguishes:
    - blocking errors (red — modelling must not proceed);
    - warnings (amber — do not block valid data);
    - retained usable data (green summary);
    - excluded/rejected data (with a CSV download when available).
    Optionally includes the region-mapping report when it has been computed.
    """
    if report is None:
        return

    has_blockers = bool(report.blocking_errors)
    with st.expander("📋 Data Quality Report", expanded=has_blockers):
        if has_blockers:
            for err in report.blocking_errors:
                st.error(f"🚫 {err}")
        else:
            st.success(
                f"✅ Parsed **{report.source_rows_read:,}** source row(s) into "
                f"**{report.observations_retained:,}** usable observation(s)."
            )

        for w in report.warnings:
            st.warning(f"⚠️ {w}")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Source rows read", f"{report.source_rows_read:,}")
        m1.metric("Source rows removed", f"{report.source_rows_removed:,}")
        m2.metric("Observations retained", f"{report.observations_retained:,}")
        m2.metric("Observations removed", f"{report.observations_removed:,}")
        m3.metric("Regions detected", f"{len(report.raw_regions):,}")
        m3.metric("Duplicate key rows", f"{report.duplicate_key_rows:,}")
        m4.metric("Frequency", report.inferred_frequency)
        if report.date_range is not None:
            m4.metric(
                "Date range",
                f"{report.date_range[0].date()} → {report.date_range[1].date()}",
            )

        with st.expander("Excluded / rejected data", expanded=has_blockers):
            st.markdown(
                f"- **{report.observations_dropped_missing_kpi:,}** observation(s) dropped for a "
                "missing KPI value.\n"
                f"- **{report.observations_dropped_non_numeric_kpi:,}** observation(s) dropped "
                "for a non-numeric KPI value.\n"
                f"- **{report.observations_dropped_invalid_date:,}** observation(s) dropped for "
                "an invalid date.\n"
                f"- **{report.source_rows_dropped_blank_region:,}** source row(s) dropped for a "
                "blank region."
            )
            if report.missing_dates:
                shown = ", ".join(d.strftime("%d %b %y") for d in report.missing_dates[:10])
                more = (
                    f" (+{len(report.missing_dates) - 10} more)"
                    if len(report.missing_dates) > 10
                    else ""
                )
                st.markdown(
                    f"- **{len(report.missing_dates):,}** expected date(s) missing "
                    f"({report.expected_date_count:,} expected at "
                    f"{report.inferred_frequency} frequency): {shown}{more}"
                )
            if rejected_rows is not None and len(rejected_rows):
                st.download_button(
                    "⬇️ Download rejected rows (CSV)",
                    data=rejected_rows.to_csv(index=False).encode("utf-8"),
                    file_name="kpi_rejected_rows.csv",
                    mime="text/csv",
                    key="kpi_rejected_rows_download",
                )

        if mapping_report is not None:
            _render_mapping_quality(mapping_report)


def _render_mapping_quality(mapping_report):
    """Render the region-mapping quality block (mapped/unmapped + download)."""
    st.markdown("**Region mapping**")
    m1, m2, m3 = st.columns(3)
    m1.metric("Raw regions", f"{len(mapping_report.raw_regions):,}")
    m2.metric("Mapped regions", f"{len(mapping_report.mapped_regions):,}")
    m3.metric("Unmapped regions", f"{len(mapping_report.unmapped_regions):,}")
    if mapping_report.unmapped_regions:
        shown = ", ".join(mapping_report.unmapped_regions[:20])
        if len(mapping_report.unmapped_regions) > 20:
            shown += ", …"
        st.warning(f"⚠️ Unmapped regions: {shown}")
        if mapping_report.unmapped_rows is not None and len(mapping_report.unmapped_rows):
            st.download_button(
                "⬇️ Download unmapped rows (CSV)",
                data=mapping_report.unmapped_rows.to_csv(index=False).encode("utf-8"),
                file_name="kpi_unmapped_rows.csv",
                mime="text/csv",
                key="kpi_unmapped_rows_download",
            )


def apply_geo_aggregation(df_long, geo_col):
    agg_df = df_long.groupby(["date", "region"])["kpi"].sum().reset_index()
    return agg_df


def format_range(lower, upper, suffix="", decimals=1):
    """
    Consistently formats a (lower, upper) range as "{lower}{suffix} to {upper}{suffix}",
    e.g. "0.1% to 21.0%" or "-50 to 120". Returns "N/A" if either value is missing or
    not finite (covers None, np.nan, pd.NA, and +/-inf).
    Used everywhere range values are shown in the Method Comparison table so ranges
    never mix bracket-style formatting (e.g. "[0.1%, 21.0%]") with "to"-style formatting.
    """
    if lower is None or upper is None:
        return "N/A"
    try:
        if pd.isna(lower) or pd.isna(upper):
            return "N/A"
    except (TypeError, ValueError):
        return "N/A"
    try:
        if not np.isfinite(float(lower)) or not np.isfinite(float(upper)):
            return "N/A"
    except (TypeError, ValueError):
        return "N/A"
    fmt = f"{{:.{decimals}f}}"
    return f"{fmt.format(lower)}{suffix} to {fmt.format(upper)}{suffix}"


def build_chart_data_xlsx(sheets):
    """
    Builds an in-memory .xlsx workbook (as bytes) from one or more DataFrames, for use
    with st.download_button() next to a chart — lets users export the exact data behind
    a Plotly chart, since Plotly's own modebar only exports a PNG snapshot, not data.

    sheets: dict of {sheet_name: DataFrame}. None values are skipped (e.g. an "Indexed"
    sheet that couldn't be computed because the pre-period average was zero) rather than
    written as an empty sheet. Sheet names are truncated to Excel's 31-character limit.

    Returns bytes ready to hand directly to st.download_button(data=...).
    """
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        wrote_any = False
        for sheet_name, df in sheets.items():
            if df is None:
                continue
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            wrote_any = True
        if not wrote_any:
            # st.download_button still needs valid bytes even if every sheet was skipped
            # (e.g. pre-period average was zero for every available sheet).
            pd.DataFrame({"Note": ["No data available for export."]}).to_excel(
                writer, sheet_name="Data", index=False
            )
    return buffer.getvalue()


# ------------------------------------------------------------
# Power analysis / Minimum Detectable Effect (Design mode)
# ------------------------------------------------------------
# LEGACY: compute_power_curve() and find_mde() are the exploratory empirical
# detectability preview based on placebo uplift percentages. They are NOT the
# approved prospective Power Analysis and Test Sizing product (see
# docs/product/power-analysis-and-test-sizing.md). Do not extend them into the
# new power feature without an approved methodology decision.
def compute_power_curve(placebo_uplift_pcts, effect_grid_pct=None, alpha=0.05):
    """
    Empirical power curve for a geo-test design, derived from the placebo
    (fake-test) uplift-% distribution — no model refitting required.

    Logic: injecting a synthetic uplift of +x% into a placebo window multiplies
    that window's fake-test actuals by (1 + x/100) while leaving the model fit
    untouched (training data precedes the window), so the window's measured
    uplift-% shifts in closed form:

        lift:    measured_pct = placebo_pct * (1 + x/100) + x
        decline: measured_pct = placebo_pct * (1 - x/100) - x

    "Detected" means the shifted uplift-% crosses a one-sided empirical
    threshold from the no-effect placebo distribution: its (1 - alpha) quantile
    for lifts, its alpha quantile for declines. Power at effect size x is the
    share of placebo windows that would have been detected.

    Caveats (surfaced in the UI): the same finite placebo sample provides both
    the null threshold and the power estimate; overlapping windows are
    positively correlated; and the approach assumes future noise behaves like
    pre-period noise. Resolution is limited to ~1 / n_windows.

    Returns a DataFrame with columns [effect_pct, power_lift, power_drop];
    empty if fewer than 5 valid placebo windows are available.
    """
    if placebo_uplift_pcts is None:
        placebo_uplift_pcts = []
    pcts = np.asarray(
        [p for p in placebo_uplift_pcts if _is_valid_number(p)],
        dtype=float,
    )
    if len(pcts) < 5:
        return pd.DataFrame(columns=["effect_pct", "power_lift", "power_drop"])
    if effect_grid_pct is None:
        effect_grid_pct = np.round(np.arange(0.5, 30.0 + 1e-9, 0.5), 2)
    thr_hi = np.percentile(pcts, (1.0 - alpha) * 100)
    thr_lo = np.percentile(pcts, alpha * 100)
    rows = []
    for x in effect_grid_pct:
        shifted_up = pcts * (1.0 + x / 100.0) + x
        shifted_dn = pcts * (1.0 - x / 100.0) - x
        rows.append(
            {
                "effect_pct": float(x),
                "power_lift": float(np.mean(shifted_up > thr_hi)),
                "power_drop": float(np.mean(shifted_dn < thr_lo)),
            }
        )
    return pd.DataFrame(rows)


def find_mde(power_df, column, target_power=0.8):
    """Smallest effect size (%) whose empirical power meets target_power, or None."""
    if power_df is None or power_df.empty or column not in power_df.columns:
        return None
    hit = power_df[power_df[column] >= target_power]
    return float(hit["effect_pct"].iloc[0]) if not hit.empty else None


@st.cache_data(ttl=CONFIG["cache_ttl"], show_spinner=False)
def _cached_rolling_origin_validation(
    X,
    y,
    frequency_config,
    horizon=4,
    min_training_periods=13,
    dates=None,
    n_splits=5,
    model_type="enet",
    min_training_weeks=None,
):
    """st.cache_data wrapper over the pure rolling-origin validation.

    Preserves the previous caching behaviour (avoid refitting up to ~20 folds on
    every Streamlit rerun); the pure function itself is cache-free.
    """
    return rolling_origin_validation(
        X,
        y,
        frequency_config,
        horizon=horizon,
        min_training_periods=min_training_periods,
        dates=dates,
        n_splits=n_splits,
        model_type=model_type,
        min_training_weeks=min_training_weeks,
    )


def run_validation_method(
    agg_df,
    control_list,
    test_regions,
    method_name,
    pre_start,
    pre_end,
    test_start=None,
    test_end=None,
    use_post=False,
    post_start=None,
    post_end=None,
    compute_uplift=True,
    placebo_length_weeks=None,
    min_training_weeks=13,
    include_lagged_controls=False,
    time_series_frequency="weekly",
    placebo_length_periods=None,
    min_training_periods=None,
    frequency_config=None,
):
    """Thin Streamlit adapter over the pure validation service.

    Renders the pure service's structured warnings/errors/blockers (see
    geotestlab.validation.service.run_validation) and returns the legacy result
    dict so the existing UI keeps working unchanged. Returns None when there is
    insufficient pre-period data to fit any model.
    """
    if frequency_config is None:
        frequency_config = get_frequency_config(time_series_frequency)
    if placebo_length_periods is None:
        placebo_length_periods = placebo_length_weeks
    if min_training_periods is None:
        min_training_periods = min_training_weeks if min_training_weeks is not None else 13

    config = ValidationConfig(
        method_name=method_name,
        compute_uplift=compute_uplift,
        placebo_length_periods=placebo_length_periods,
        min_training_periods=min_training_periods,
        include_lagged_controls=include_lagged_controls,
        time_series_frequency=time_series_frequency,
        frequency_config=frequency_config,
    )
    periods = ValidationPeriods(
        pre_start=pd.to_datetime(pre_start),
        pre_end=pd.to_datetime(pre_end),
        test_start=pd.to_datetime(test_start) if test_start is not None else None,
        test_end=pd.to_datetime(test_end) if test_end is not None else None,
        use_post=use_post,
        post_start=pd.to_datetime(post_start) if use_post and post_start is not None else None,
        post_end=pd.to_datetime(post_end) if use_post and post_end is not None else None,
    )
    result = run_validation(
        agg_df,
        control_list,
        test_regions,
        config,
        periods,
        rolling_origin_fn=_cached_rolling_origin_validation,
    )
    for w in result.warnings:
        st.warning(w)
    for e in result.errors:
        st.error(e)
    if result.blockers:
        for b in result.blockers:
            st.error(b)
        st.stop()
    if result.insufficient_pre_period:
        return None
    return result.to_dict()


def repair_text_value(v):
    if not isinstance(v, str):
        return v
    s = v.strip()
    try:
        repaired = s.encode("latin1").decode("utf-8")
        s = repaired
    except Exception:
        pass
    s = s.replace("--", "–")
    return unicodedata.normalize("NFC", s)


def clean_dataframe_text(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # pandas 3.0 stores strings in the new "str" dtype by default, so selecting
    # only "object" would silently miss them (and raises a Pandas4Warning).
    # "object" + "string" selects text columns on both pandas 2.x and 3.x —
    # see the pandas 3.0 string migration guide.
    text_cols = df.select_dtypes(include=["object", "string"]).columns
    for c in text_cols:
        df[c] = df[c].map(repair_text_value)
    return df


def inspect_excel_sheet(path: str, sheet_name: str) -> dict:
    try:
        df_raw = pd.read_excel(
            path,
            sheet_name=sheet_name,
            engine="calamine",
            header=None,
            dtype=str,
            keep_default_na=False,
        )
        issues = []
        for row_idx, row in df_raw.iterrows():
            for col_idx, val in enumerate(row):
                if val and str(val).startswith("#"):
                    issues.append({"row": row_idx, "col": col_idx, "value": val})
        return {"has_issues": len(issues) > 0, "issues": issues[:10], "total_issues": len(issues)}
    except Exception as e:
        return {"has_issues": True, "error": str(e)}


# ------------------------------------------------------------
# Excel workbook loading
# ------------------------------------------------------------
# The workbook/sheet readers are cached on (path, sheet, identity) so a
# same-path replacement of the bundled workbook (same-size or not) changes
# the identity and invalidates the Streamlit caches.
@st.cache_data(ttl=CONFIG["cache_ttl"])
def get_workbook_sheet_names(path: str, identity=None) -> list[str]:
    xl = pd.ExcelFile(path, engine="calamine")
    return xl.sheet_names


@st.cache_data(ttl=CONFIG["cache_ttl"])
def load_market_sheet(path: str, sheet_name: str, identity=None) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, engine="calamine", dtype=str)
    except Exception:
        try:
            df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", dtype=str)
        except Exception as e2:
            st.error(f"Failed to load sheet with both engines: {e2}")
            raise
    df = normalise_column_names(df)
    error_patterns = ["#N/A", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!"]
    df = df.replace(error_patterns, pd.NA)
    df = clean_dataframe_text(df)
    df = df.dropna(axis=1, how="all")
    df = df.dropna(axis=0, how="all")
    df["Market"] = sheet_name
    return df


@st.cache_data(ttl=CONFIG["cache_ttl"])
def aggregate_market_data(
    market_df: pd.DataFrame, grouping_col: str, numeric_metric_cols: list[str]
) -> pd.DataFrame:
    """Streamlit-cached wrapper over the pure geotestlab.matching.aggregate_market_data."""
    return _aggregate_market_data(
        market_df, grouping_col, numeric_metric_cols, population_col=POPULATION_COL
    )


@st.cache_data(ttl=CONFIG["cache_ttl"], show_spinner=False)
def read_kpi_pattern_excel(file_bytes: bytes) -> pd.DataFrame:
    """Parses the uploaded KPI Pattern workbook, cached on the file's raw bytes.
    Streamlit reruns the whole script on every widget interaction, and this file was
    previously parsed twice per rerun (sidebar peek + main tab) — with caching it is
    parsed once per unique upload, no matter how many reruns occur."""
    return _read_kpi_pattern_excel(file_bytes)


# ------------------------------------------------------------
# Matching metric helpers
# ------------------------------------------------------------
@st.cache_data(ttl=CONFIG["cache_ttl"])
def calculate_metrics_cached(
    test_df, control_df, features_tuple, weights_tuple, eligible_means_tuple, eligible_stds_tuple
):
    """Streamlit-cached wrapper over the pure geotestlab.matching scorer."""
    return calculate_metrics_from_flat(
        test_df,
        control_df,
        features_tuple,
        weights_tuple,
        eligible_means_tuple,
        eligible_stds_tuple,
    )


@st.cache_data(ttl=CONFIG["cache_ttl"])
def preprocess_data(
    pool_df, test_df_run, active_features, weights, eligible_means_tuple, eligible_stds_tuple
):
    """Streamlit-cached wrapper over the pure geotestlab.matching.preprocess_data.

    Nearest-neighbour candidate search uses the SAME fixed eligible-pool basis
    (eligible_means/eligible_stds) as calculate_metrics(), so the NN ranking is
    consistent with the Weighted Structural Distance objective."""
    return _preprocess_data(
        pool_df, test_df_run, active_features, weights, eligible_means_tuple, eligible_stds_tuple
    )


# ------------------------------------------------------------
# Validation and display helpers
# ------------------------------------------------------------
def validate_data(df, required_cols, geo_col=None, market=None, level=None):
    issues = []
    recommendations = []
    if len(df) == 0:
        issues.append("❌ No data available for the selected filters")
        recommendations.append("💡 Try a different market or geography grouping")
        return issues, recommendations
    if not required_cols:
        issues.append("⚠️ No numeric matching features detected")
        recommendations.append("💡 Check that demographic columns are numeric")
        return issues, recommendations
    missing_pct = df[required_cols].isnull().mean() * 100
    high_missing = missing_pct[missing_pct > CONFIG["missing_threshold"]]
    if len(high_missing) > 0:
        issues.append(
            f"📊 High missing values (> {CONFIG['missing_threshold']}%): {dict(high_missing)}"
        )
        recommendations.append(
            f"💡 Consider removing from matching: {', '.join(high_missing.index[:3])}"
        )
    constant_cols = []
    for col in required_cols:
        if df[col].nunique(dropna=False) <= 1:
            constant_cols.append(col)
    if constant_cols:
        issues.append(f"⚠️ Constant features detected: {constant_cols[:5]}")
        recommendations.append(
            f"💡 Remove these features because they do not help matching: {', '.join(constant_cols[:3])}"
        )
    outlier_dict = {}
    for col in required_cols:
        if df[col].count() > 10:
            clean_data = df[col].dropna()
            if len(clean_data) > 0 and clean_data.std() > 0:
                z_scores = np.abs(stats.zscore(clean_data))
                outlier_mask = z_scores > CONFIG["outlier_std_threshold"]
                if outlier_mask.any():
                    outlier_indices = clean_data.index[outlier_mask]
                    if geo_col and len(outlier_indices) > 0:
                        outlier_regions = df.loc[outlier_indices, geo_col].tolist()
                    else:
                        outlier_regions = ["Unknown"]
                    outlier_dict[col] = outlier_regions[:3]
    if outlier_dict:
        issues.append(f"🔴 Extreme outliers detected (> {CONFIG['outlier_std_threshold']} std dev)")
        for col, regions in list(outlier_dict.items())[:3]:
            issues.append(f"   • {col}: {', '.join(str(r) for r in regions)}")
        recommendations.append(
            "💡 Investigate outlier regions for data errors or consider excluding them"
        )
    if len(df) < 3:
        issues.append(f"⚠️ Very small sample size: {len(df)} geographies")
        recommendations.append("💡 Try a more granular geography grouping, if available")
    return issues, recommendations


def _clear_bayesian_state():
    """Clear Bayesian results AND the (potentially large) posterior trace.

    The trace key is REMOVED (not set to None) so the InferenceData object can
    be garbage-collected; every reset family must clear the trace alongside the
    results.
    """
    st.session_state.bayesian_results = None
    st.session_state.bayesian_interpretation_visible = False
    st.session_state.pop("bayesian_trace", None)


def _clear_production_power_state():
    """Clear cached production and candidate-scenario power results."""

    st.session_state.production_power_result = None
    st.session_state.production_power_config = None
    st.session_state.power_scenario_result = None
    st.session_state.power_scenario_config = None


def reset_results():
    st.session_state.final_controls = None
    st.session_state.test_df = None
    st.session_state.opt_results = {}
    st.session_state.match_mode_res = None
    st.session_state.best_n = None
    st.session_state.w_reset = st.session_state.get("w_reset", 0) + 1
    st.session_state.guided_share_info = None
    st.session_state.selected_experiment_regions = []
    st.session_state.user_selected_mode = False
    st.session_state.user_control_geos = []
    st.session_state.match_run_snapshot = None
    st.session_state.match_run_metrics = None
    st.session_state.match_results_stale = False
    # Test/control regions are changing — any downstream time-series validation and
    # Bayesian TBR results were computed against the old region set and are now stale.
    st.session_state.validation_results = None
    st.session_state.validation_triggered = False
    _clear_bayesian_state()
    _clear_production_power_state()
    # Experiment record inputs are cleared too — the record reconciles these
    # stages to "stale" on the next rerun (Stage 4).
    st.session_state.experiment_matching_inputs = None
    st.session_state.experiment_validation_inputs = None
    st.session_state.experiment_bayesian_inputs = None
    st.session_state.kpi_pattern_source_bytes = None
    st.session_state.kpi_pattern_regional_dataset = None
    st.session_state.kpi_pattern_date_range = None


def reset_manual_results():
    """Clear matching results but keep manual selections (test/control geos)."""
    st.session_state.final_controls = None
    st.session_state.test_df = None
    st.session_state.opt_results = {}
    st.session_state.match_mode_res = None
    st.session_state.best_n = None
    st.session_state.guided_share_info = None
    st.session_state.selected_experiment_regions = []
    st.session_state.match_run_snapshot = None
    st.session_state.match_run_metrics = None
    st.session_state.match_results_stale = False
    # Do NOT reset user_control_geos or user_selected_mode
    # Test/control regions are changing — any downstream time-series validation and
    # Bayesian TBR results were computed against the old region set and are now stale.
    st.session_state.validation_results = None
    st.session_state.validation_triggered = False
    _clear_bayesian_state()
    _clear_production_power_state()
    # Experiment record inputs are cleared too — the record reconciles these
    # stages to "stale" on the next rerun (Stage 4).
    st.session_state.experiment_matching_inputs = None
    st.session_state.experiment_validation_inputs = None
    st.session_state.experiment_bayesian_inputs = None
    st.session_state.kpi_pattern_source_bytes = None
    st.session_state.kpi_pattern_regional_dataset = None
    st.session_state.kpi_pattern_date_range = None


def matching_setup_changed_since_last_run(
    run_snapshot, market, geography_level, match_mode, test_geos, weights
):
    """
    Compare the CURRENT live setup against the frozen snapshot saved at the time of the
    last completed Run Match Analysis click. Returns True if anything that would affect
    the displayed results (market, geography level, strategy, test regions, or slider
    weights) has changed since that run, so the UI can warn the user that the cards below
    are stale rather than silently recomputing them from live widget state.
    """
    if not run_snapshot:
        return False
    if market != run_snapshot.get("market"):
        return True
    if geography_level != run_snapshot.get("geography_level"):
        return True
    if match_mode != run_snapshot.get("match_mode"):
        return True
    if run_snapshot.get("guided_seed") != GUIDED_SEARCH_CONFIG.seed:
        return True
    if set(test_geos) != set(run_snapshot.get("test_geos", [])):
        return True
    run_weights = run_snapshot.get("weights", {}) or {}
    if dict(weights) != dict(run_weights):
        return True
    return False


def is_proportion_series(series):
    s = series.dropna()
    if s.empty:
        return False
    return (s.min() >= 0) and (s.max() <= 1)


def format_numeric_value(col_name, val, proportion_cols):
    if pd.isna(val):
        return ""
    if col_name == "Population Density":
        return f"{val:,.1f}"
    if col_name in proportion_cols:
        return f"{val * 100:.1f}%"
    if abs(val) >= 1000:
        return f"{val:,.1f}"
    if abs(val) >= 10:
        return f"{val:.2f}"
    return f"{val:.3f}"


def format_percentage(value, decimals=1):
    """Shared formatter for test/control share cards, the target caption, the
    closest-achieved-share warning, and text exports. Formats only for display —
    never rounds the value before it's stored in session state or exports."""
    return f"{value:.{decimals}f}%"


def format_display_df(df, proportion_cols):
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].apply(lambda v: format_numeric_value(c, v, proportion_cols))
    return out


def standardize_column_order(df, geo_col, active_features):
    base_order = ["Market", geo_col, POPULATION_COL]
    if "Population Density" in df.columns:
        base_order.append("Population Density")
    remaining = [c for c in df.columns if c not in base_order]
    ordered = [c for c in base_order if c in df.columns] + remaining
    return df[ordered]


def cleanup_session_state():
    if (
        st.session_state.get("final_controls") is not None
        and len(st.session_state.final_controls) > 100
    ):
        df = st.session_state.final_controls
        # Always keep geo_col and POPULATION_COL; fill remaining slots with other feature cols
        must_keep = [c for c in [geo_col, POPULATION_COL] if c in df.columns]
        other_cols = [c for c in df.columns if c not in must_keep]
        keep = must_keep + list(other_cols[: CONFIG["max_display_features"]])
        st.session_state.final_controls = df[keep]


# =============================================================================
# Experiment record (Stage 4): identity, deterministic input fingerprints,
# explicit stage status, stale-result propagation, frozen approved design
# versions, planned-vs-analysed comparison, and a reproducible local export.
# The pure logic lives in geotestlab.experiment; these adapters only bridge it
# to session state / Streamlit widgets.
# =============================================================================
# Tool / methodology versions recorded in frozen design snapshots (Stage 2).
# The tool version is derived from installed package metadata (must match
# pyproject.toml), with a tested development fallback — never hardcoded here.
GEOTESTLAB_TOOL_VERSION = tool_version()
# Follows the power-analysis methodology spike; not an approved ADR.
GEOTESTLAB_METHODOLOGY_VERSION = "0.2.0"


def _experiment_record() -> ExperimentRecord:
    """Load the current experiment record from session state (creating one if needed)."""
    data = st.session_state.get("experiment_record")
    if not data:
        rec = create_experiment_record()
        st.session_state.experiment_record = rec.to_dict()
        return rec
    return ExperimentRecord.from_dict(data)


def _save_experiment_record(rec: ExperimentRecord) -> None:
    st.session_state.experiment_record = rec.to_dict()


def _iso_date(v):
    if v is None:
        return None
    try:
        return pd.Timestamp(v).isoformat()
    except Exception:
        return str(v)


def _live_matching_inputs():
    """Deterministic dict of the current live matching inputs (module-scope safe)."""
    _geo = globals().get("geography_level")
    _geo_col = globals().get("geo_col", _geo)
    controls = st.session_state.get("final_controls")
    control_regions = (
        sorted(controls[_geo_col].dropna().astype(str).tolist())
        if controls is not None and _geo_col in controls.columns
        else []
    )
    return {
        "matching_method": st.session_state.get("matching_method_sidebar"),
        "market": globals().get("market"),
        "geography_level": _geo,
        "kpi_pattern_mode": st.session_state.get("kpi_pattern_mode", False),
        "kpi_pattern_agg_col": st.session_state.get("kpi_pattern_agg_col_sidebar"),
        "kpi_pattern_metric_value": st.session_state.get("kpi_pattern_metric_value_sidebar"),
        "test_regions": sorted(
            str(r) for r in (st.session_state.get("selected_experiment_regions", []) or [])
        ),
        "control_regions": control_regions,
        "weights": dict(st.session_state.get("current_weights") or {}),
    }


def _experiment_input_summary():
    """Human-readable summary of the current workflow inputs (for the record)."""
    matching = _live_matching_inputs() or {}
    validation = st.session_state.get("experiment_validation_inputs") or {}
    return {
        "matching_method": matching.get("matching_method"),
        "market": matching.get("market"),
        "geography_level": matching.get("geography_level"),
        "test_region_count": len(matching.get("test_regions", []) or []),
        "control_region_count": len(matching.get("control_regions", []) or []),
        "kpi_file_name": validation.get("kpi_file_name"),
        "selected_metric": validation.get("selected_metric"),
        "time_series_frequency": validation.get("time_series_frequency"),
        "test_start": validation.get("test_start"),
        "test_end": validation.get("test_end"),
    }


def _workbook_identity():
    """Material identity of the bundled workbook (path, size, mtime_ns)."""
    return material_file_identity(DATA_PATH)


def _workbook_identity_tuple():
    """Hashable material identity (tuple) for Streamlit cache keys."""
    ident = _workbook_identity()
    if ident is None:
        return None
    return (ident["path"], ident["size"], ident["mtime_ns"])


def _cached_workbook_bytes():
    """Bundled geography workbook bytes, cached by material file identity
    (path + size + mtime_ns, never size alone — a same-size replacement is
    detected and invalidates the cache)."""
    key = _workbook_identity()
    if key is None:
        return None
    cached = st.session_state.get("experiment_geo_workbook_cache")
    if cached and cached[0] == key:
        return cached[1]
    try:
        with open(DATA_PATH, "rb") as f:
            data = f.read()
    except Exception:
        return None
    st.session_state.experiment_geo_workbook_cache = (key, data)
    return data


def _cached_market_sheet(market=None):
    """Selected market sheet, cached by (market, workbook identity) so the
    sheet is invalidated whenever the workbook material identity changes.

    ``market`` defaults to the session-stored current market (set by the
    sidebar), falling back to a module-level global if one exists.
    """
    if market is None:
        market = st.session_state.get("current_market") or globals().get("market")
    if not market:
        return None
    key = ("sheet", str(market), _workbook_identity())
    cached = st.session_state.get("experiment_market_sheet_cache")
    if cached and cached[0] == key:
        return cached[1]
    try:
        df = load_market_sheet(DATA_PATH, market, _workbook_identity_tuple())
    except Exception:
        df = None
    st.session_state.experiment_market_sheet_cache = (key, df)
    return df


def _current_candidate_universe(agg_df, geo_col):
    """Candidate region universe for the current inputs (data + selected
    test/control regions) — the same set the mapping recompute uses."""
    test = st.session_state.get("selected_experiment_regions", []) or []
    controls = st.session_state.get("final_controls")
    control = (
        controls[geo_col].tolist() if controls is not None and geo_col in controls.columns else []
    )
    return sorted(
        set(agg_df[geo_col].dropna().astype(str).str.strip().unique().tolist())
        | set(test)
        | set(control)
    )


def _current_candidate_universe_digest(agg_df, geo_col):
    """SHA-256 identity of the current candidate region universe."""
    return candidate_universe_digest(_current_candidate_universe(agg_df, geo_col))


def _current_mapping_reference_digest(geo_col, market=None):
    """SHA-256 identity of the raw->canonical mapping reference (adobe_to_geo).

    KPI Pattern mode has no structural mapping reference (empty dict). The
    structural reference comes from the cached market sheet, so no re-read per
    rerun is needed.
    """
    if st.session_state.get("kpi_pattern_mode"):
        ref = {}
    else:
        master = _cached_market_sheet(market=market)
        if master is None:
            return None
        try:
            ref = dict(
                zip(
                    master[ADOBE_COL].astype(str).str.strip(),
                    master[geo_col].astype(str).str.strip(),
                )
            )
        except Exception:
            return None
    return compute_input_fingerprint(ref)


def _compute_content_digests():
    """Content-level SHA-256 identities for the current workflow inputs.

    Digests only — raw content is never stored in the record/export.
    """
    return build_content_digests(
        source_bytes=st.session_state.get("kpi_source_bytes"),
        analytical_data=st.session_state.get("kpi_long_df"),
        workbook_bytes=_cached_workbook_bytes(),
        market_sheet=_cached_market_sheet(market=st.session_state.get("current_market")),
        candidate_universe=st.session_state.get("kpi_candidate_universe"),
    )


def _freeze_value(value):
    """Convert an executed stage value into a bounded JSON-safe snapshot."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, np.generic):
        return _freeze_value(value.item())
    if hasattr(value, "to_dict"):
        return _freeze_value(value.to_dict())
    if is_dataclass(value):
        return _freeze_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _freeze_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_freeze_value(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _dependency_versions() -> dict[str, str]:
    """Capture only dependency metadata useful for reproducing this export."""
    names = ("geotestlab", "streamlit", "pandas", "numpy", "scipy", "plotly", "altair")
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def _current_design_snapshot(*, analyst_label="", analyst_notes=(), approval_timestamp=None):
    """Complete design snapshot for freezing (available values only; never
    fabricated platform/spend values).

    The matching section is reconstructed from the EXECUTED match snapshot
    (``match_run_snapshot``), not the live widget state. Region exclusions are
    kept strictly separate from time-period exclusions. Data-quality fields
    are stored separately (never a collapsed/uncovered-regions read)."""
    rec = _experiment_record()
    snapshot = st.session_state.get("match_run_snapshot")
    matching = st.session_state.get("experiment_matching_inputs") or {}
    validation = st.session_state.get("experiment_validation_inputs") or {}
    analysed = rec.analysed or {}
    _map = st.session_state.get("kpi_mapping_report")
    _q = st.session_state.get("kpi_quality_report")
    _rejected = st.session_state.get("kpi_rejected_rows")
    if snapshot:
        test_regions = sorted(str(r) for r in (snapshot.get("test_geos") or []))
        control_regions = sorted(str(r) for r in (snapshot.get("selected_controls") or []))
        matching_section = build_frozen_matching_section(snapshot)
    else:
        test_regions = sorted(matching.get("test_regions", []) or [])
        control_regions = sorted(matching.get("control_regions", []) or [])
        matching_section = {
            "matching_method": matching.get("matching_method"),
            "kpi_pattern_mode": matching.get("kpi_pattern_mode"),
            "feature_weights": dict(matching.get("weights") or {}),
        }
    required_regions = test_regions or (
        st.session_state.get("selected_experiment_regions", []) or []
    )
    quality_summary = build_frozen_data_quality_summary(
        mapping_report=_map,
        required_regions=required_regions,
        blocking_errors=_quality_blocking_errors(),
        warnings=(tuple(getattr(_q, "warnings", ()) or ()) if _q is not None else ()),
        observations={
            "observations_retained": getattr(_q, "observations_retained", None),
            "observations_removed": getattr(_q, "observations_removed", None),
            "duplicate_key_rows": getattr(_q, "duplicate_key_rows", None),
            "rejected_rows": len(_rejected) if _rejected is not None else 0,
        },
    )
    result_summaries = _result_summaries_for_export()
    dataset = st.session_state.get("kpi_regional_dataset")
    power_config = st.session_state.get("production_power_config")
    power_result = st.session_state.get("production_power_result")
    scenario_config = st.session_state.get("power_scenario_config")
    scenario_result = st.session_state.get("power_scenario_result")
    selected_candidate = getattr(scenario_result, "selected_candidate", None)
    selected_candidate_power = getattr(selected_candidate, "power_result", None)
    media_result = st.session_state.get("media_delivery_result")
    media_plan = st.session_state.get("media_delivery_plan")
    effect_result = st.session_state.get("effect_plausibility_result")
    effect_evidence = getattr(effect_result, "evidence", None) if effect_result else None
    recommendation = st.session_state.get("design_recommendation_result")
    recommendation_dict = _freeze_value(recommendation) if recommendation else None
    recommendation_objective = st.session_state.get("design_recommendation_objective")
    if recommendation_objective is None:
        recommendation_objective = (recommendation_dict or {}).get("objective")
    selected_candidate_dict = _freeze_value(selected_candidate) if selected_candidate else {}
    power_config_dict = _freeze_value(power_config or scenario_config)
    power_result_for_snapshot = power_result or selected_candidate_power
    power_result_dict = _freeze_value(power_result_for_snapshot)
    planned_campaign_dates = (
        (power_result_dict or {}).get("planned_test_dates")
        or (power_config_dict or {}).get("planned_test_dates")
        or selected_candidate_dict.get("planned_test_dates", [])
    )
    planned_duration = (
        (power_result_dict or {}).get("planned_duration_periods")
        or (power_config_dict or {}).get("planned_duration_periods")
        or selected_candidate_dict.get("duration_periods")
    )
    region_exclusions = matching_section.get("region_exclusions") or {}
    excluded_regions = sorted(
        {str(region) for regions in region_exclusions.values() for region in (regions or [])}
    )
    validation_methods = sorted(
        str(method)
        for method in (st.session_state.get("validation_results") or {}).get("results", {})
    )
    source_fingerprint = getattr(dataset, "source_data_fingerprint", None)
    if source_fingerprint is None:
        source_fingerprint = getattr(_q, "source_data_fingerprint", None)
    media_status = getattr(getattr(media_result, "status", None), "value", None)
    media_section = {
        "status": "completed" if media_result is not None else "not_supplied",
        "platform_profile": getattr(media_plan, "profile_id", None),
        "budget": _freeze_value(
            (media_plan.to_dict() if media_plan else {}).get("values", {}).get("total_budget")
        ),
        "forecast_and_provenance": _freeze_value(media_plan),
        "result": _freeze_value(media_result),
        "delivery_status": media_status,
    }
    effect_section = {
        "status": "completed" if effect_result is not None else "not_supplied",
        "evidence": _freeze_value(effect_evidence),
        "scenarios": _freeze_value(getattr(effect_evidence, "scenarios", ()))
        if effect_evidence
        else [],
        "result": _freeze_value(effect_result),
    }
    power_section = {
        "status": "completed" if power_result_for_snapshot is not None else "not_supplied",
        "configuration": power_config_dict,
        "result": power_result_dict,
        "mde": (power_result_dict or {}).get("mde"),
        "support_status": (power_result_dict or {}).get("support_status", "not_supplied"),
        "limitations": {
            "blockers": (power_result_dict or {}).get("blockers", []),
            "warnings": (power_result_dict or {}).get("warnings", []),
            "errors": (power_result_dict or {}).get("errors", []),
        },
    }
    return {
        "experiment_identity": {"experiment_id": rec.experiment_id},
        "experiment_id": rec.experiment_id,
        "market": matching_section.get("market"),
        "geography_level": matching_section.get("geography_level"),
        "aggregation": validation.get("kpi_agg_col"),
        "classification": snapshot.get("geo_col") if snapshot else None,
        "frequency": validation.get("time_series_frequency"),
        "source_data_fingerprint": source_fingerprint,
        "data_quality_summary": quality_summary,
        "source_data_quality": _freeze_value(_q),
        "test_regions": test_regions,
        "control_regions": control_regions,
        "kpi": {
            "file_name": validation.get("kpi_file_name"),
            "file_size": validation.get("kpi_file_size"),
            "selected_metric": validation.get("selected_metric"),
            "agg_col": validation.get("kpi_agg_col"),
            "time_series_frequency": validation.get("time_series_frequency"),
        },
        "historical_period": {
            "pre_start": validation.get("pre_start"),
            "pre_end": validation.get("pre_end"),
        },
        "planned_test_period": {
            "test_start": validation.get("test_start"),
            "test_end": validation.get("test_end"),
            "use_post": validation.get("use_post"),
            "post_start": validation.get("post_start"),
            "post_end": validation.get("post_end"),
            "planned_test_periods": analysed.get("planned_test_periods"),
            "analysed_test_periods": analysed.get("analysed_test_periods"),
            "excluded_test_periods": analysed.get("excluded_test_periods"),
        },
        "matching": matching_section,
        "seeds": {
            "matching_seed": (
                snapshot.get("guided_seed") if snapshot else None
            ),  # actual guided seed when executed
        },
        "validation_settings": {
            "include_lagged_controls": validation.get("include_lagged_controls"),
            "min_training_periods": validation.get("min_training_periods"),
            "placebo_length_periods": validation.get("placebo_length_periods"),
        },
        "excluded_regions": excluded_regions,
        "matching_metrics": _freeze_value(st.session_state.get("match_run_metrics") or {}),
        "matching_method": matching_section.get("matching_method"),
        "matching_strategy": matching_section.get("executed_strategy"),
        "validation": {
            "method": validation_methods,
            "settings": {
                "include_lagged_controls": validation.get("include_lagged_controls"),
                "min_training_periods": validation.get("min_training_periods"),
                "placebo_length_periods": validation.get("placebo_length_periods"),
            },
            "summary": result_summaries.get("counterfactual_validation", {}),
        },
        "validation_method": validation_methods,
        "validation_summary": result_summaries.get("counterfactual_validation", {}),
        "source_data_digests": dict(validation.get("content_digests") or {}),
        "time_period_exclusions": {
            "manual": sorted(validation.get("manual_excluded_dates", []) or []),
            "tracking_outages": sorted(validation.get("auto_flagged_dates", []) or []),
        },
        "tool_version": GEOTESTLAB_TOOL_VERSION,
        "methodology_version": GEOTESTLAB_METHODOLOGY_VERSION,
        "planned_campaign_dates": planned_campaign_dates,
        "planned_duration_periods": planned_duration,
        "power": power_section,
        "power_configuration": power_config_dict,
        "power_result": power_result_dict,
        "power_support_status": power_section["support_status"],
        "power_limitations": power_section["limitations"],
        "scenario_sizing": {
            "configuration": _freeze_value(scenario_config),
            "result": _freeze_value(scenario_result),
            "market_size_measure": selected_candidate_dict.get(
                "market_size_measure", getattr(scenario_result, "market_size_measure", None)
            ),
            "requested_test_share": selected_candidate_dict.get("requested_share"),
            "achieved_test_share": selected_candidate_dict.get("actual_share"),
        },
        "market_size_measure": selected_candidate_dict.get(
            "market_size_measure", getattr(scenario_result, "market_size_measure", None)
        ),
        "requested_test_share": selected_candidate_dict.get("requested_share")
        or matching_section.get("test_share", {}).get("target"),
        "achieved_test_share": selected_candidate_dict.get("actual_share")
        or matching_section.get("test_share", {}).get("achieved"),
        "media_delivery": media_section,
        "media_platform_profile": media_section["platform_profile"],
        "media_budget": media_section["budget"],
        "media_delivery_forecast": media_section["forecast_and_provenance"],
        "media_delivery_result": media_section["result"],
        "effect_plausibility": effect_section,
        "effect_evidence": effect_section["evidence"],
        "effect_scenarios": effect_section["scenarios"],
        "recommendation": {
            "status": "completed" if recommendation else "not_supplied",
            "result": recommendation_dict,
            "objective": _freeze_value(recommendation_objective),
            "scenarios": _freeze_value(st.session_state.get("design_recommendation_scenarios", ())),
            "override": {
                "scenario_id": (recommendation_dict or {}).get("override_scenario_id"),
                "reason": (recommendation_dict or {}).get("override_reason"),
                "applied": bool((recommendation_dict or {}).get("override_applied", False)),
            },
        },
        "recommendation_result": recommendation_dict,
        "recommendation_objective": _freeze_value(recommendation_objective),
        "package_metadata": {
            "package": "geotestlab",
            "package_version": GEOTESTLAB_TOOL_VERSION,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "dependencies": _dependency_versions(),
        },
        "approval": {
            "timestamp": approval_timestamp,
            "analyst_label": str(analyst_label or "").strip(),
            "analyst_notes": [str(note) for note in (analyst_notes or ()) if str(note).strip()],
        },
        "analyst": {
            "label": str(analyst_label or "").strip(),
            "notes": [str(note) for note in (analyst_notes or ()) if str(note).strip()],
        },
    }


def _stamp_match_quality():
    """Stamp the match_quality stage with the current matching-input fingerprint."""
    if st.session_state.get("final_controls") is None:
        return
    inputs = _live_matching_inputs()
    st.session_state.experiment_matching_inputs = inputs
    rec = _experiment_record()
    record_stage_result(rec, "match_quality", compute_input_fingerprint(inputs))
    _save_experiment_record(rec)


def _stamp_validation_stage():
    """Stamp counterfactual_validation (and observed_impact when the completed-test
    evaluation succeeds) and store the analysed-period summary."""
    vres = st.session_state.get("validation_results") or {}
    if not vres:
        return
    matching = st.session_state.get("experiment_matching_inputs") or {}
    validation_inputs = dict(st.session_state.get("experiment_validation_inputs") or {})
    # Content-level SHA-256 identities are part of the validation identity.
    digests = _compute_content_digests()
    validation_inputs["content_digests"] = digests
    st.session_state.experiment_validation_inputs = validation_inputs
    fp = compute_input_fingerprint({**matching, **validation_inputs})
    rec = _experiment_record()
    rec.content_digests = dict(digests)
    record_stage_result(rec, "counterfactual_validation", fp)
    rec.analysed = {
        "pre_start": _iso_date(vres.get("pre_start")),
        "pre_end": _iso_date(vres.get("pre_end")),
        "test_start": _iso_date(vres.get("test_start")),
        "test_end": _iso_date(vres.get("test_end")),
        "use_post": bool(vres.get("use_post", False)),
        "post_start": _iso_date(vres.get("post_start")),
        "post_end": _iso_date(vres.get("post_end")),
        "time_series_frequency": vres.get("time_series_frequency", "weekly"),
        "planned_test_periods": vres.get("planned_test_periods"),
        "analysed_test_periods": vres.get("analysed_test_periods"),
        "excluded_test_periods": (vres.get("planned_test_periods") or 0)
        - (vres.get("analysed_test_periods") or 0),
    }
    # observed_impact is completed ONLY by a genuinely successful completed-test
    # evaluation (Evaluate mode, a completed evaluation service run, at least one
    # successful method result with a finite observed-impact value, and no
    # blocker for that method). Design-mode validation or failed evaluations
    # never complete the stage.
    if observed_impact_completed(vres):
        record_stage_result(rec, "observed_impact", fp)
    _save_experiment_record(rec)


def _stamp_bayesian_stage():
    """Record the Bayesian TBR as an additional method result under
    observed_impact (the stage is completed by the completed-test evaluation;
    a Bayesian run is not required for observed impact)."""
    bayesian_inputs = st.session_state.get("experiment_bayesian_inputs") or {}
    if not bayesian_inputs:
        return
    matching = st.session_state.get("experiment_matching_inputs") or {}
    validation = st.session_state.get("experiment_validation_inputs") or {}
    fp = compute_input_fingerprint({**matching, **validation, **bayesian_inputs})
    rec = _experiment_record()
    record_stage_method_result(rec, "observed_impact", "bayesian_tbr", fp)
    _save_experiment_record(rec)


def _reconcile_experiment_record():
    """Recompute current stage fingerprints each rerun and propagate staleness."""
    rec = _experiment_record()
    has_matching = st.session_state.get("final_controls") is not None
    matching = _live_matching_inputs() if has_matching else None
    validation = st.session_state.get("experiment_validation_inputs") or None
    bayesian = st.session_state.get("experiment_bayesian_inputs") or None
    power_config = st.session_state.get("production_power_config")
    power_dataset = st.session_state.get("kpi_regional_dataset")
    media_result = st.session_state.get("media_delivery_result")
    media_plan = st.session_state.get("media_delivery_plan")
    media_thresholds = st.session_state.get("media_delivery_thresholds")
    media_scope = st.session_state.get("media_delivery_scope")
    effect_result = st.session_state.get("effect_plausibility_result")
    if "effect_plausibility_current_evidence" in st.session_state:
        effect_evidence = st.session_state.effect_plausibility_current_evidence
    else:
        effect_evidence = st.session_state.get("effect_plausibility_evidence")

    current = {}
    full = {}
    if matching:
        current["match_quality"] = compute_input_fingerprint(matching)
        full.update(matching)
    if matching and validation:
        current["counterfactual_validation"] = compute_input_fingerprint({**matching, **validation})
        current["observed_impact"] = compute_input_fingerprint({**matching, **validation})
        full.update(validation)
    if bayesian:
        full.update(bayesian)
    if power_config is not None and power_dataset is not None:
        power_fp = production_input_fingerprint(power_dataset, power_config)
        current["statistical_power"] = power_fp
        full.update({"statistical_power": power_config.to_dict(), "power_source": power_fp})

    if media_result is not None and all(
        value is not None for value in (media_plan, media_thresholds, media_scope)
    ):
        media_fp = delivery_input_fingerprint(media_plan, media_thresholds, media_scope)
        current["media_delivery"] = media_fp
        result_fp = str(media_result.input_fingerprint or "")
        if result_fp and rec.stage_fingerprints.get("media_delivery") != result_fp:
            record_stage_result(rec, "media_delivery", result_fp)

    if effect_result is not None and effect_evidence is not None:
        media_fp = current.get("media_delivery")
        if media_result is None or media_fp:
            effect_fp = effect_input_fingerprint(
                effect_evidence,
                st.session_state.get("effect_plausibility_current_mde"),
                st.session_state.get("effect_plausibility_current_direction", "two_sided"),
                delivery_status=media_result.status.value if media_result else None,
                delivery_fingerprint=media_fp,
            )
            current["effect_plausibility"] = effect_fp
            result_fp = str(effect_result.input_fingerprint or "")
            if result_fp and rec.stage_fingerprints.get("effect_plausibility") != result_fp:
                record_stage_result(rec, "effect_plausibility", result_fp)

    if full:
        update_inputs(rec, compute_input_fingerprint(full), _experiment_input_summary())

    # A stage that produced a result before but now has no current inputs (the app
    # cleared it because the setup changed) is explicitly stale.
    for stage in STAGE_KEYS:
        if (
            stage in rec.stage_fingerprints
            and stage not in current
            and rec.stage_status.get(stage) not in ("planned", "not_applicable", "not_started")
        ):
            rec.stage_stale[stage] = True
            rec.stage_status[stage] = "stale"
    propagate_staleness(rec, current)
    _save_experiment_record(rec)


def _lifecycle_status_rows() -> list[dict[str, str]]:
    """Return visible Plan/Evaluate status rows without changing stage semantics."""

    rec = _experiment_record()
    recommendation = st.session_state.get("design_recommendation_result")
    recommendation_value = getattr(getattr(recommendation, "status", None), "value", None)
    if recommendation is None:
        recommendation_status = "not_started"
    elif st.session_state.get("design_recommendation_stale", False):
        recommendation_status = "needs_attention"
    elif recommendation_value in {"recommended", "conditional"}:
        recommendation_status = "completed"
    else:
        recommendation_status = "needs_attention"

    bayesian_status = (
        "completed" if st.session_state.get("bayesian_results") is not None else "not_started"
    )
    lifecycle = (
        ("match_quality", "Match quality", "Plan a Test"),
        ("counterfactual_validation", "Counterfactual validation", "Plan a Test"),
        ("statistical_power", "Power & test sizing", "Plan a Test"),
        ("media_delivery", "Media delivery", "Plan a Test"),
        ("effect_plausibility", "Effect plausibility", "Plan a Test"),
        ("recommendation", "Design recommendation / approval", "Plan a Test"),
        ("observed_impact", "Measure test impact", "Evaluate a Completed Test"),
        ("bayesian", "Bayesian TBR", "Evaluate a Completed Test"),
    )
    rows = []
    for key, label, phase in lifecycle:
        stale = bool(rec.stage_stale.get(key, False)) if key in STAGE_KEYS else False
        status = (
            recommendation_status
            if key == "recommendation"
            else bayesian_status
            if key == "bayesian"
            else rec.stage_status.get(key, "not_started")
        )
        if stale or status == "stale":
            status = "needs_attention"
        rows.append({"Lifecycle": phase, "Stage": label, "Status": status})
    return rows


def render_lifecycle_status_summary() -> None:
    """Render the workflow map and the next action outside collapsible panels."""

    rows = _lifecycle_status_rows()
    st.subheader("Workflow status")
    st.caption(
        "Plan a Test covers matching through design approval. Evaluate a Completed Test covers "
        "observed impact and Bayesian TBR. Statuses remain separate; a warning is never a pass."
    )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    attention = next(
        (row for row in rows if row["Status"] in {"stale", "needs_attention"}),
        None,
    )
    next_step = next(
        (
            row
            for row in rows
            if row["Status"] not in {"completed", "not_applicable"}
            and row["Status"] not in {"stale", "needs_attention"}
        ),
        None,
    )
    if attention:
        st.warning(
            f"Needs attention: {attention['Stage']} is {attention['Status']}. "
            "Re-run it after correcting or confirming its upstream inputs."
        )
    elif next_step:
        st.info(
            f"Next recommended action: open **{next_step['Stage']}** in the "
            f"**{next_step['Lifecycle']}** workflow."
        )
    else:
        st.success("All displayed lifecycle stages have current results.")


def _current_planned_periods():
    """Current planned periods from the latest validation run (for freezing)."""
    vres = st.session_state.get("validation_results") or {}
    if not vres.get("results"):
        return None
    _planned = vres.get("planned_test_periods")
    _analysed = vres.get("analysed_test_periods")
    return {
        "pre_start": _iso_date(vres.get("pre_start")),
        "pre_end": _iso_date(vres.get("pre_end")),
        "test_start": _iso_date(vres.get("test_start")),
        "test_end": _iso_date(vres.get("test_end")),
        "use_post": bool(vres.get("use_post", False)),
        "post_start": _iso_date(vres.get("post_start")),
        "post_end": _iso_date(vres.get("post_end")),
        "time_series_frequency": vres.get("time_series_frequency", "weekly"),
        "planned_test_periods": _planned,
        "analysed_test_periods": _analysed,
        "excluded_test_periods": (_planned or 0) - (_analysed or 0)
        if _planned is not None
        else None,
    }


def _result_summaries_for_export():
    """Build the complete serialisable result section for the current record."""

    return build_unified_result_summaries(
        validation_results=st.session_state.get("validation_results"),
        bayesian_results=st.session_state.get("bayesian_results"),
        power_result=st.session_state.get("production_power_result"),
        power_config=st.session_state.get("production_power_config"),
        media_delivery_result=st.session_state.get("media_delivery_result"),
        media_delivery_plan=st.session_state.get("media_delivery_plan"),
        media_delivery_thresholds=st.session_state.get("media_delivery_thresholds"),
        media_delivery_scope=st.session_state.get("media_delivery_scope"),
        effect_plausibility_result=st.session_state.get("effect_plausibility_result"),
        recommendation_result=st.session_state.get("design_recommendation_result"),
        recommendation_scenarios=st.session_state.get("design_recommendation_scenarios", ()),
        recommendation_objective=st.session_state.get("design_recommendation_objective"),
    )


def _render_mcmc_diagnostics(bayes: dict, trace) -> None:
    """Render MCMC diagnostics from a posterior trace.

    Called only when ``trace`` is present — the caller guards rendering when the
    trace is missing (e.g. after a reset or a file change), so the large
    ``InferenceData`` object can be dropped without crashing the results view.
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
        ess_min_threshold=CONFIG["ess_min_threshold"],
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
                f"Your min ESS: {diag['min_ess']:.0f} (guidance = ≥{CONFIG['ess_min_threshold']})."
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
                or (pd.notna(ess_bulk) and ess_bulk < CONFIG["ess_min_threshold"])
                or (pd.notna(ess_tail) and ess_tail < CONFIG["ess_min_threshold"])
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
                f"⚠️ {diag['n_divergences']} divergent transition(s) occurred during sampling. "
                "Divergences aren't tied to a specific parameter row the way R-hat/ESS/MCSE are, "
                "so they aren't reflected in the highlighting above — see the Divergences card and "
                "warning above the table instead."
            )
        st.caption(
            "Rows highlighted in red fail at least one of: R-hat > 1.01, ESS bulk or tail "
            f"< {CONFIG['ess_min_threshold']}, or MCSE/SD ≥ 10%."
        )


def render_experiment_record():
    """Stage 4 UI: identity, stage statuses, design freeze, planned-vs-analysed, export."""
    rec = _experiment_record()
    _status_icon = {
        "not_started": "⚪",
        "planned": "🔵",
        "in_progress": "🔄",
        "completed": "🟢",
        "stale": "🟠",
        "not_applicable": "⚪",
    }
    with st.expander("🧪 Experiment record & design freeze", expanded=False):
        st.caption(f"**Experiment ID:** `{rec.experiment_id}`")
        st.caption(f"**Created:** {rec.created_at} · **Updated:** {rec.updated_at}")
        if rec.input_fingerprint:
            st.caption(f"**Input fingerprint:** `{rec.input_fingerprint}`")
        else:
            st.caption("**Input fingerprint:** not yet computed — run matching to start.")

        st.markdown("**Workflow stage statuses**")
        for key, label in STAGE_LABELS.items():
            status = rec.stage_status.get(key, "not_started")
            stale = rec.stage_stale.get(key, False)
            suffix = " — inputs changed, re-run" if stale else ""
            st.caption(f"{_status_icon.get(status, '⚪')} **{label}:** {status}{suffix}")

        st.markdown("**Design freeze**")
        _planned = _current_planned_periods()
        _recommendation = st.session_state.get("design_recommendation_result")
        _recommendation_status = getattr(getattr(_recommendation, "status", None), "value", None)
        _recommendation_ready = (
            _recommendation is not None
            and not st.session_state.get("design_recommendation_stale", False)
            and _recommendation_status in {"recommended", "conditional"}
        )
        _approval_inputs_stale = any(
            rec.stage_stale.get(stage, False)
            for stage in (
                "match_quality",
                "counterfactual_validation",
                "statistical_power",
                "media_delivery",
                "effect_plausibility",
            )
        )
        if _approval_inputs_stale:
            st.caption(
                "One or more upstream results are stale; re-run those stages before approval."
            )
        if not _recommendation_ready:
            st.caption(
                "Complete a current design recommendation before freezing an approved design. "
                "A stale, incomplete, or non-qualifying recommendation cannot be approved."
            )
        _analyst_label = st.text_input("Analyst label (optional)", key="freeze_analyst_label")
        _analyst_notes = st.text_area(
            "Analyst notes (optional)", key="freeze_analyst_notes", height=80
        )
        _can_freeze = (
            bool(_planned)
            and bool(rec.input_fingerprint)
            and _recommendation_ready
            and not _approval_inputs_stale
        )
        if st.button(
            "🧊 Freeze approved design",
            key="freeze_design_btn",
            disabled=not _can_freeze,
            help=(
                "Capture the executed matching and analytical results, planned test periods, "
                "and input fingerprint as an immutable approved design version."
            ),
        ):
            _approval_time = datetime.now(UTC)
            _approval_timestamp = utc_now_iso(_approval_time)
            freeze_design(
                rec,
                _planned,
                rec.input_fingerprint,
                label=_analyst_label.strip(),
                design=_current_design_snapshot(
                    analyst_label=_analyst_label,
                    analyst_notes=_analyst_notes.splitlines(),
                    approval_timestamp=_approval_timestamp,
                ),
                now=_approval_time,
            )
            _save_experiment_record(rec)
            st.success(
                f"Design frozen as version {active_frozen_version(rec)['version']} "
                f"({rec.experiment_id})."
            )

        _cmp = planned_vs_analysed(rec)
        st.markdown("**Planned vs analysed**")
        if _cmp["frozen"]:
            st.caption(f"Frozen version {_cmp['version']} at {_cmp['frozen_at']}.")
            st.caption(
                "Frozen version history: "
                + ", ".join(
                    f"v{version.version} ({version.frozen_at})" for version in rec.frozen_versions
                )
                + f". Active version: v{_cmp['version']}."
            )
            if _cmp["matches"]:
                st.success("✅ Analysed periods match the frozen design.")
            else:
                st.warning("⚠️ Analysed periods differ from the frozen design:")
                for diff in _cmp["differences"]:
                    st.caption(f"- {diff}")
            if _cmp.get("design_changed_since_freeze"):
                st.warning(
                    "🟠 Live workflow inputs differ from the active frozen design. "
                    "Run the affected stages and freeze a new version; existing versions "
                    "remain unchanged."
                )
        else:
            st.caption("No frozen design version yet — run an evaluation and freeze it.")

        st.markdown("**Reproducible export**")
        _export = build_experiment_export(rec, result_summaries=_result_summaries_for_export())
        st.download_button(
            "⬇️ Export experiment record (.json)",
            data=json.dumps(_export, indent=2, default=str),
            file_name=f"{rec.experiment_id}.json",
            mime="application/json",
            key="export_experiment_record_json",
        )
        st.caption(
            "The export is a local serialisable record — no database is used. It captures "
            "identity, input fingerprint, stage statuses, frozen design versions, "
            "planned-vs-analysed, and unified validation, power, delivery, effect and "
            "recommendation result summaries."
        )


# ------------------------------------------------------------
# Session state initialisation
# ------------------------------------------------------------
if "final_controls" not in st.session_state:
    st.session_state.final_controls = None
if "test_df" not in st.session_state:
    st.session_state.test_df = None
if "opt_results" not in st.session_state:
    st.session_state.opt_results = {}
if "match_mode_res" not in st.session_state:
    st.session_state.match_mode_res = None
if "best_n" not in st.session_state:
    st.session_state.best_n = None
if "w_reset" not in st.session_state:
    st.session_state.w_reset = 0
if "guided_share_info" not in st.session_state:
    st.session_state.guided_share_info = None
if "selected_experiment_regions" not in st.session_state:
    st.session_state.selected_experiment_regions = []
if "user_selected_mode" not in st.session_state:
    st.session_state.user_selected_mode = False
if "user_control_geos" not in st.session_state:
    st.session_state.user_control_geos = []
if "match_run_snapshot" not in st.session_state:
    st.session_state.match_run_snapshot = None
if "match_run_metrics" not in st.session_state:
    st.session_state.match_run_metrics = None
if "match_results_stale" not in st.session_state:
    st.session_state.match_results_stale = False

# ---- Experiment record (Stage 4) ----
if "experiment_record" not in st.session_state:
    st.session_state.experiment_record = create_experiment_record().to_dict()
if "experiment_matching_inputs" not in st.session_state:
    st.session_state.experiment_matching_inputs = None
if "experiment_validation_inputs" not in st.session_state:
    st.session_state.experiment_validation_inputs = None
if "experiment_bayesian_inputs" not in st.session_state:
    st.session_state.experiment_bayesian_inputs = None

# ------------------------------------------------------------
# Load workbook and market
# ------------------------------------------------------------
try:
    available_markets = sorted(get_workbook_sheet_names(DATA_PATH, _workbook_identity_tuple()))
except Exception as e:
    st.error(
        "We couldn't load the geography/population data file this app relies on. Please check that the data file is present and correctly formatted."
    )
    with st.expander("Technical details"):
        st.code(f"{type(e).__name__}: {e}")
    st.stop()

_default_market_index = available_markets.index("UK") if "UK" in available_markets else 0

with st.sidebar:
    st.header("Matching Method")
    matching_method = st.radio(
        "Matching method",
        ["Structural", "KPI Pattern"],
        key="matching_method_sidebar",
        on_change=reset_results,
        help="**Structural** matches test/control regions on demographic profile (age, income, etc.) "
        "from the built-in population dataset.\n\n"
        "**KPI Pattern** matches regions on the shape of their own historical KPI trend instead — "
        "use this when demographic data for your regions (e.g. custom TV/zip-code-derived regions) "
        "isn't readily available.",
    )
    kpi_pattern_mode = matching_method == "KPI Pattern"
    st.session_state["kpi_pattern_mode"] = kpi_pattern_mode
    st.write("---")

    kpi_pattern_file = None
    kpi_pattern_agg_col = None
    kpi_pattern_metric_value = None
    kpi_pattern_date_range = None

    if not kpi_pattern_mode:
        st.header("1. Geography")
        market = st.selectbox(
            "Market",
            available_markets,
            index=_default_market_index,
            on_change=reset_results,
            help="Select the market whose regions you want to use for geo-testing.",
        )
        st.session_state["current_market"] = market
    else:
        st.header("1. Data Source")
        kpi_pattern_file = st.file_uploader(
            "Upload aggregated KPI file",
            type=["xlsx"],
            key="kpi_pattern_sidebar_uploader",
            help="Column 1: raw key, not used (e.g. postcode). Columns 2..N-1: aggregation levels "
            "(e.g. TV Market, TV Region). One column named 'Metric': metric name. Remaining "
            "columns: one per date (weekly or daily).",
            on_change=reset_results,
        )
        market = "KPI Pattern"
        st.session_state["current_market"] = market
        if kpi_pattern_file is not None:
            st.session_state["kpi_pattern_source_bytes"] = kpi_pattern_file.getvalue()
            _kp_peek = read_kpi_pattern_excel(kpi_pattern_file.getvalue())
            _kp_date_cols = detect_date_columns(_kp_peek)
            _kp_non_date_cols = [c for c in _kp_peek.columns if c not in _kp_date_cols]
            if len(_kp_non_date_cols) < 3 or not _kp_date_cols:
                st.error(
                    "File format not recognized — need a raw-key column, at least one aggregation-level "
                    "column, a metric column, and date columns."
                )
            else:
                _kp_metric_col = detect_metric_column(_kp_non_date_cols)
                if _kp_metric_col is None:
                    st.error(
                        "Couldn't find a column named 'Metric'. Please rename your metric-name column to 'Metric'."
                    )
                else:
                    st.session_state["kpi_pattern_metric_col"] = _kp_metric_col
                    _kp_agg_candidates = [c for c in _kp_non_date_cols[1:] if c != _kp_metric_col]
                    kpi_pattern_agg_col = st.selectbox(
                        "Aggregation level",
                        _kp_agg_candidates,
                        key="kpi_pattern_agg_col_sidebar",
                        on_change=reset_results,
                        help="Which column to group and sum by — this becomes your geography level for matching.",
                    )
                    _kp_metric_values = sorted(_kp_peek[_kp_metric_col].dropna().unique().tolist())
                    kpi_pattern_metric_value = st.selectbox(
                        "Metric",
                        _kp_metric_values,
                        key="kpi_pattern_metric_value_sidebar",
                        on_change=reset_results,
                    )
                    _kp_dates_sorted = sorted(_kp_date_cols)
                    _kp_date_labels = [d.strftime("%d %b %y") for d in _kp_dates_sorted]
                    _kp_label_to_date = dict(zip(_kp_date_labels, _kp_dates_sorted))
                    st.caption(
                        "This should be the **pre-period** — the historical window regions are "
                        "matched on. Exclude any dates that fall inside your planned test period."
                    )
                    _kp_date_col1, _kp_date_col2 = st.columns(2)
                    with _kp_date_col1:
                        _kp_start_label = st.selectbox(
                            "Start date",
                            _kp_date_labels,
                            index=0,
                            key="kpi_pattern_date_start_sidebar",
                            on_change=reset_results,
                        )
                    with _kp_date_col2:
                        _kp_end_label = st.selectbox(
                            "End date",
                            _kp_date_labels,
                            index=len(_kp_date_labels) - 1,
                            key="kpi_pattern_date_end_sidebar",
                            on_change=reset_results,
                        )
                    _kp_start_date = _kp_label_to_date[_kp_start_label]
                    _kp_end_date = _kp_label_to_date[_kp_end_label]
                    if _kp_start_date >= _kp_end_date:
                        st.error("Start date must be before end date.")
                        kpi_pattern_date_range = None
                    else:
                        kpi_pattern_date_range = (_kp_start_date, _kp_end_date)
                    st.session_state["kpi_pattern_date_range"] = kpi_pattern_date_range

if not kpi_pattern_mode:
    try:
        market_df_raw = load_market_sheet(DATA_PATH, market, _workbook_identity_tuple())
        market_df = prepare_market_dataframe(market_df_raw)
        grouping_options = get_grouping_columns(market_df)
    except Exception as e:
        st.error(
            f"We couldn't prepare the data for market '{market}'. Please check that this market's sheet is formatted correctly."
        )
        with st.expander("Technical details"):
            st.code(f"{type(e).__name__}: {e}")
        st.stop()

    with st.sidebar:
        geography_level = st.selectbox(
            "Geography Level",
            grouping_options,
            on_change=reset_results,
            help="The geographic unit to match on — e.g. region, state, or city.",
        )
        st.write("---")
        st.header("2. Matching Strategy")
        strategy_labels = {
            "Basic (Fast)": "Greedy (Nearest Neighbor)",
            "Intermediate (Balanced)": "Refined Greedy (Hill Climbing)",
            "Advanced (Thorough)": "Stochastic (Genetic Search)",
        }
        strategy_choice = st.radio(
            "Strategy",
            list(strategy_labels.keys()),
            index=0,
            on_change=reset_results,
            help="Controls how thoroughly GeoMatch searches for the best control group.\n\n"
            "**Basic** uses nearest-neighbour matching — fast but may miss better combinations.\n\n"
            "**Intermediate** refines the nearest-neighbour result by trying local swaps.\n\n"
            "**Advanced** uses stochastic swap search across many candidate combinations. It is slower than Intermediate, but explores more possible control groups without exhaustively testing every combination.",
        )
        match_mode = strategy_labels[strategy_choice]

    # ------------------------------------------------------------
    # Aggregate selected market
    # ------------------------------------------------------------
    geo_col = geography_level
    active_features = get_numeric_metric_columns(market_df, grouping_options)

    agg_df = aggregate_market_data(
        market_df=market_df, grouping_col=geo_col, numeric_metric_cols=active_features
    )
    agg_df = impute_missing_features(agg_df, active_features)
    agg_df = agg_df.dropna(subset=[geo_col, POPULATION_COL])
    agg_df = agg_df[agg_df[POPULATION_COL] > 0]

    total_market_pop = agg_df[POPULATION_COL].sum()
    st.session_state["power_population_weights"] = {
        str(region): float(weight)
        for region, weight in zip(agg_df[geo_col], agg_df[POPULATION_COL])
    }
else:
    with st.sidebar:
        st.write("---")
        st.header("2. Matching Strategy")
        strategy_labels = {
            "Basic (Fast)": "Greedy (Nearest Neighbor)",
            "Intermediate (Balanced)": "Refined Greedy (Hill Climbing)",
            "Advanced (Thorough)": "Stochastic (Genetic Search)",
        }
        strategy_choice = st.radio(
            "Strategy",
            list(strategy_labels.keys()),
            index=0,
            on_change=reset_results,
            help="Controls how thoroughly GeoMatch searches for the best control group.\n\n"
            "**Basic** uses nearest-neighbour matching — fast but may miss better combinations.\n\n"
            "**Intermediate** refines the nearest-neighbour result by trying local swaps.\n\n"
            "**Advanced** uses stochastic swap search across many candidate combinations. It is slower than Intermediate, but explores more possible control groups without exhaustively testing every combination.",
        )
        match_mode = strategy_labels[strategy_choice]

    if (
        kpi_pattern_file is None
        or kpi_pattern_agg_col is None
        or kpi_pattern_metric_value is None
        or kpi_pattern_date_range is None
    ):
        st.info(
            "📂 Upload an aggregated KPI file and complete the selections in the sidebar to continue."
        )
        st.stop()

    _kp_full = read_kpi_pattern_excel(kpi_pattern_file.getvalue())
    _kp_metric_col_full = st.session_state["kpi_pattern_metric_col"]
    _kp_date_cols_full = detect_date_columns(_kp_full)
    _kp_dates_in_range = [
        d
        for d in sorted(_kp_date_cols_full)
        if kpi_pattern_date_range[0] <= d <= kpi_pattern_date_range[1]
    ]
    if len(_kp_dates_in_range) < 2:
        st.error("Select a wider date range in the sidebar — at least 2 dates are needed.")
        st.stop()

    _kp_dataset = prepare_regional_kpi(
        _kp_full,
        RegionalKPIConfig(
            aggregation_column=kpi_pattern_agg_col,
            metric_column=_kp_metric_col_full,
            metric_value=str(kpi_pattern_metric_value),
        ),
    )
    st.session_state["kpi_pattern_regional_dataset"] = _kp_dataset
    if _kp_dataset.data.empty:
        st.error(
            "No rows remain after filtering. Check your metric/aggregation-level/date-range selection."
        )
        st.stop()

    # The shared contract performs numeric coercion and sum(min_count=1)
    # aggregation before this KPI Pattern-specific date/outage handling.
    _kp_wide_raw_full = build_kpi_pattern_wide_from_regional(
        _kp_dataset, str(kpi_pattern_metric_value), _kp_dates_in_range
    )
    _kp_n_dropped = _kp_dataset.quality.source_rows_dropped_blank_region
    _kp_non_numeric_cells = _kp_dataset.quality.observations_dropped_non_numeric_kpi

    _kp_quality_report = compute_period_quality(_kp_wide_raw_full)
    _kp_reason_by_date = {
        row.date: "; ".join(row.reasons) for row in _kp_quality_report.rows if row.reasons
    }
    _kp_auto_flagged_dates = set(_kp_quality_report.definite_outage_dates) | set(
        _kp_quality_report.missing_period_dates
    )

    _kp_date_option_labels = []
    _kp_label_to_date = {}
    for d in _kp_dates_in_range:
        reason = _kp_reason_by_date.get(d)
        label = f"{d.strftime('%d %b %y')} — {reason}" if reason else d.strftime("%d %b %y")
        _kp_date_option_labels.append(label)
        _kp_label_to_date[label] = d

    _kp_exclude_widget_key = "kpi_pattern_outage_exclude_select"
    if _kp_exclude_widget_key not in st.session_state:
        st.session_state[_kp_exclude_widget_key] = [
            lbl for lbl, d in _kp_label_to_date.items() if d in _kp_auto_flagged_dates
        ]
    st.markdown("**Periods to exclude because of tracking or data-quality issues:**")
    _kp_selected_exclude_labels = st.multiselect(
        "kpi_pattern_outage_exclude",
        _kp_date_option_labels,
        label_visibility="collapsed",
        help=(
            "Dates that look like a market-wide tracking outage (all or almost all "
            "regions exactly zero, or most regions missing) are preselected. Add or "
            "remove dates as needed — excluded dates are dropped before matching, but "
            "remain part of the selected date range shown elsewhere."
        ),
        key=_kp_exclude_widget_key,
    )
    _kp_manual_excluded_dates = {_kp_label_to_date[lbl] for lbl in _kp_selected_exclude_labels}
    _kp_dates_retained = [d for d in _kp_dates_in_range if d not in _kp_manual_excluded_dates]
    if len(_kp_dates_retained) < 2:
        st.error(
            "Fewer than 2 dates remain after excluding flagged/selected periods — "
            "select a wider date range or exclude fewer periods."
        )
        st.stop()
    if _kp_manual_excluded_dates:
        st.caption(
            f"ℹ️ {len(_kp_dates_in_range)} period(s) in range, "
            f"{len(_kp_manual_excluded_dates)} excluded, {len(_kp_dates_retained)} retained "
            f"({len(_kp_auto_flagged_dates)} auto-flagged)."
        )

    _kp_wide_raw, _kp_incomplete_regions = retain_kpi_dates(_kp_wide_raw_full, _kp_dates_retained)
    if _kp_wide_raw.empty:
        st.error("No regions with non-zero data in this range.")
        st.stop()

    # Index each region to its own mean over the selected range = 100, for pattern matching —
    # this is what makes "distance" comparable across regions of very different raw KPI volume.
    _kp_wide_indexed = index_kpi_series_to_100(_kp_wide_raw)

    geography_level = kpi_pattern_agg_col
    geo_col = geography_level
    active_features = [f"wk_{d.strftime('%Y%m%d')}" for d in _kp_dates_retained]
    # POPULATION_COL is aliased here to mean "total KPI volume over the selected range" rather
    # than population — this is what "Test/Control Population Share" measures throughout the
    # matching UI below; user-facing labels for this are adjusted where they'd otherwise say
    # "population" (see kpi_share_label() and its call sites).
    agg_df = build_kpi_pattern_agg_df(_kp_wide_indexed, _kp_wide_raw, geo_col, active_features)
    total_market_pop = agg_df[POPULATION_COL].sum()
    # In KPI Pattern mode POPULATION_COL represents KPI volume, not population.
    st.session_state["power_population_weights"] = None

    st.session_state["kpi_pattern_wide_raw"] = _kp_wide_raw
    st.session_state["kpi_pattern_metric_value"] = kpi_pattern_metric_value
    st.session_state["kpi_pattern_dates_in_range"] = _kp_dates_retained
    st.session_state["kpi_pattern_period_quality"] = {
        "automatic_outage_dates": sorted(_kp_auto_flagged_dates),
        "manual_excluded_dates": sorted(_kp_manual_excluded_dates),
        "effective_excluded_dates": sorted(_kp_manual_excluded_dates),
        "incomplete_regions_after_exclusion": _kp_incomplete_regions,
    }

    if _kp_n_dropped > 0:
        st.caption(f"ℹ️ {_kp_n_dropped} row(s) dropped: blank '{kpi_pattern_agg_col}' value.")
    if _kp_non_numeric_cells > 0:
        st.caption(f"ℹ️ {_kp_non_numeric_cells} non-numeric date-value cell(s) treated as missing.")
    if _kp_incomplete_regions:
        st.caption(
            f"ℹ️ {len(_kp_incomplete_regions)} region(s) have a missing value on a retained "
            f"date and were excluded: {', '.join(_kp_incomplete_regions[:10])}"
            f"{'…' if len(_kp_incomplete_regions) > 10 else ''}"
        )


def kpi_share_label(base_label):
    """Relabels a "...Population..." string to "...Share of {metric}..." when in KPI Pattern
    mode, since POPULATION_COL is aliased to total KPI volume (not population) in that mode.
    Structural mode returns base_label unchanged."""
    if not st.session_state.get("kpi_pattern_mode"):
        return base_label
    metric_label = st.session_state.get("kpi_pattern_metric_value", "KPI")
    return base_label.replace("population", metric_label).replace("Population", metric_label)


def kpi_feature_date_label(feature_name):
    """Converts a KPI Pattern weekly feature column name ('wk_YYYYMMDD') into a
    'dd mmm yy' display label. Returns the name unchanged if it doesn't match that
    pattern (e.g. in Structural mode, or for the Population/geo columns)."""
    if isinstance(feature_name, str) and feature_name.startswith("wk_"):
        try:
            return pd.to_datetime(feature_name[3:], format="%Y%m%d").strftime("%d %b %y")
        except (ValueError, TypeError):
            return feature_name
    return feature_name


def kpi_pattern_display_rename_map(columns, geo_col):
    """Builds a {original_col: display_col} rename map for KPI Pattern mode tables:
    date-coded weekly feature columns -> 'dd mmm yy', and POPULATION_COL -> the metric
    label (e.g. 'Revenue') instead of 'Population'. No-op (returns {}) outside KPI
    Pattern mode."""
    if not st.session_state.get("kpi_pattern_mode"):
        return {}
    metric_label = st.session_state.get("kpi_pattern_metric_value", "KPI Total")
    rename_map = {}
    for c in columns:
        if c == POPULATION_COL:
            rename_map[c] = metric_label
        else:
            new_label = kpi_feature_date_label(c)
            if new_label != c:
                rename_map[c] = new_label
    return rename_map


# Data quality check – also warn about high missingness in features
validation_issues, recommendations = validate_data(
    agg_df, active_features, geo_col=geo_col, market=market, level=geography_level
)
issue_severity = (
    "🔴 High"
    if len(validation_issues) > 3
    else "🟡 Medium"
    if len(validation_issues) > 0
    else "🟢 None"
)

# =============================================================================
# Main app – Tabs
# =============================================================================
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(
    [
        "⚙️ Region Matching",
        "🔍 Validate Test Design",
        "📈 Power & Test Sizing",
        "📣 Media Delivery Feasibility",
        "🎯 Effect Plausibility",
        "✅ Design Recommendation / Approve Design",
        "📊 Measure Test Impact",
        "🧠 Bayesian TBR",
    ]
)

# Render a persistent status surface before any tab-local ``st.stop()`` path.
# The same slot is refreshed after the tabs complete when the rerun reaches the
# bottom of the script.
_lifecycle_status_slot = st.empty()
_reconcile_experiment_record()
with _lifecycle_status_slot.container():
    render_lifecycle_status_summary()


# =============================================================================
# TAB 1: MATCHING SETUP
# =============================================================================
def render_structural_matching_tab():
    # ------------------------------------------------------------
    # Preview data
    # ------------------------------------------------------------
    with st.expander(f"Preview data: {market} ({geography_level})", expanded=False):
        proportion_cols = {
            c for c in active_features if c in agg_df.columns and is_proportion_series(agg_df[c])
        }
        preview_df = standardize_column_order(agg_df, geo_col, active_features)
        preview_display = format_display_df(preview_df, proportion_cols)
        _rename_map = kpi_pattern_display_rename_map(preview_display.columns, geo_col)
        if _rename_map:
            preview_display = preview_display.rename(columns=_rename_map)
        st.dataframe(preview_display, width="stretch", height=240)

    # ------------------------------------------------------------
    # Matching setup
    # ------------------------------------------------------------
    st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
    st.subheader("🧩 MATCHING SETUP")
    setup_mode = st.radio(
        "Setup Mode",
        [
            "Manual Selection (Pick Both)",
            "Pick Test, Auto‑Match Controls",
            "Set Rules & Auto‑Build Groups",
        ],
        horizontal=True,
        help="Choose how to define your test and control groups.\n\n"
        "**Manual Selection** — you pick both groups directly, no automated matching.\n\n"
        "**Pick Test, Auto‑Match Controls** — you choose the test regions and the app finds the best-matched controls.\n\n"
        "**Set Rules & Auto‑Build Groups** — define inclusion/exclusion rules and the app builds both groups.",
    )
    st.markdown("<div style='margin: 0.6rem 0;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
    st.markdown("<div style='margin: 0.4rem 0;'></div>", unsafe_allow_html=True)

    # ----------------------------------------------------------------------
    # Three-mode UI
    # ----------------------------------------------------------------------
    sel_col1, sel_col2 = st.columns(2, gap="large")
    all_geo_values = sorted(agg_df[geo_col].dropna().unique())

    # ----------------------------------------------------------------------
    # COLUMN 1 – Test Group
    # ----------------------------------------------------------------------
    with sel_col1:
        st.subheader("A. Test Group")

        total_pop = agg_df[POPULATION_COL].sum()
        geo_options_with_pop = []
        for geo in all_geo_values:
            geo_pop = agg_df[agg_df[geo_col] == geo][POPULATION_COL].sum()
            pop_pct = (geo_pop / total_pop) * 100
            geo_options_with_pop.append(f"{geo} ({pop_pct:.1f}%)")
        label_to_geo = {label: geo for label, geo in zip(geo_options_with_pop, all_geo_values)}

        if setup_mode == "Manual Selection (Pick Both)":
            st.markdown(
                "Select geographies to <span style='color:#15803d;font-weight:600'>include</span> in test group:",
                unsafe_allow_html=True,
            )
            selected_test_labels = st.multiselect(
                "test_geos_manual",
                geo_options_with_pop,
                on_change=reset_manual_results,
                help="Population percentage of total market shown in brackets. These will be the test regions.",
                label_visibility="collapsed",
            )
            test_geos = [label_to_geo[label] for label in selected_test_labels]
            if test_geos:
                test_pop_pct = calculate_experiment_population_coverage(
                    test_geos, agg_df, geo_col, total_market_pop
                )
                st.metric(
                    kpi_share_label("Test group market population included"),
                    format_percentage(test_pop_pct),
                    help=kpi_share_label(
                        "Percentage of the total market population covered by the selected test regions."
                    ),
                )
            global_exclude = []
            force_exp_include = []
            force_exp_exclude = []
            force_ctrl_include = []
            force_ctrl_exclude = []
            target_test_share = 25
            target_tolerance_pp = 5
            guided_iterations = 2000

        elif setup_mode == "Pick Test, Auto‑Match Controls":
            st.markdown(
                "Select geographies to <span style='color:#15803d;font-weight:600'>include</span> in test group:",
                unsafe_allow_html=True,
            )
            selected_labels = st.multiselect(
                "select_geographies",
                geo_options_with_pop,
                on_change=reset_results,
                help="Population percentage of total market shown in brackets",
                label_visibility="collapsed",
            )
            test_geos = [label_to_geo[label] for label in selected_labels]
            if test_geos:
                test_pop_pct = calculate_experiment_population_coverage(
                    test_geos, agg_df, geo_col, total_market_pop
                )
                st.metric(
                    kpi_share_label("Test group market population included"),
                    format_percentage(test_pop_pct),
                    help=kpi_share_label(
                        "Percentage of the total market population covered by the selected test geographies. Larger test groups are typically more representative of the overall market, but leave fewer regions available for control selection."
                    ),
                )
            global_exclude = []
            force_exp_include = []
            force_exp_exclude = []
            force_ctrl_include = []
            force_ctrl_exclude = []
            target_test_share = 25
            target_tolerance_pp = 5
            guided_iterations = 2000

        else:  # "Set Rules & Auto‑Build Groups"
            st.markdown(
                "Geographies to <span style='color:#dc2626;font-weight:600'>exclude from both</span> test and control:",
                unsafe_allow_html=True,
            )
            selected_global_exclude_labels = st.multiselect(
                "global_exclude",
                geo_options_with_pop,
                label_visibility="collapsed",
                help=(
                    "Removes a region from both the test and control candidate pools "
                    "entirely — the preferred way to drop a region from the experiment. "
                    "It stays part of the total market population used as the share "
                    "denominator, so shares are not recalculated on a smaller market."
                ),
                key="global_exclude_select",
            )
            global_exclude = [label_to_geo[label] for label in selected_global_exclude_labels]

            st.markdown(
                "Test geographies to force <span style='color:#15803d;font-weight:600'>include:</span>",
                unsafe_allow_html=True,
            )
            # A persisted selection is never silently dropped when it would
            # conflict with another rule — it stays selectable so the run's
            # structured conflict blocker (validate_constraints) surfaces it.
            _exp_include_persisted = {
                label_to_geo[lbl] for lbl in st.session_state.get("exp_include_select", [])
            }
            selected_include_labels = st.multiselect(
                "exp_include",
                [
                    label
                    for label in geo_options_with_pop
                    if label_to_geo[label] in _exp_include_persisted
                    or label_to_geo[label] not in global_exclude
                ],
                label_visibility="collapsed",
                key="exp_include_select",
            )
            force_exp_include = [label_to_geo[label] for label in selected_include_labels]
            _exp_exclude_persisted = {
                label_to_geo[lbl] for lbl in st.session_state.get("exp_exclude_select", [])
            }
            exclude_options = [
                label
                for label in geo_options_with_pop
                if label_to_geo[label] in _exp_exclude_persisted
                or (
                    label_to_geo[label] not in force_exp_include
                    and label_to_geo[label] not in global_exclude
                )
            ]
            st.markdown(
                "Test geographies to force <span style='color:#dc2626;font-weight:600'>exclude:</span>",
                unsafe_allow_html=True,
            )
            selected_exclude_labels = st.multiselect(
                "exp_exclude",
                exclude_options,
                label_visibility="collapsed",
                help=(
                    "Excluded from the TEST group only — these regions remain available "
                    "for the control pool. To remove a region from the analysis entirely, "
                    "use the 'exclude from both' field above instead."
                ),
                key="exp_exclude_select",
            )
            force_exp_exclude = [label_to_geo[label] for label in selected_exclude_labels]
            force_ctrl_include = []
            force_ctrl_exclude = []
            target_test_share = st.slider(
                kpi_share_label("Target test population share"),
                5,
                80,
                25,
                1,
                help=kpi_share_label(
                    "Desired percentage of the total market population to include in the test group. A larger test group is more representative but leaves fewer regions available as controls."
                ),
                key="target_share_slider",
            )
            target_tolerance_pp = st.slider(
                kpi_share_label("Population share tolerance (± pp)"),
                1,
                30,
                5,
                1,
                help=kpi_share_label(
                    "Acceptable deviation from the target population share, in percentage points."
                ),
                key="tolerance_slider",
            )
            guided_iterations = st.slider(
                "Search intensity",
                500,
                10000,
                2000,
                500,
                help="Number of candidate test groups evaluated. Higher values increase the chance of finding a better group but take longer to run.",
                key="guided_iterations_slider",
            )
            test_geos = []  # filled later

    # ----------------------------------------------------------------------
    # COLUMN 2 – Control Group
    # ----------------------------------------------------------------------
    with sel_col2:
        st.subheader("B. Control Group")

        if setup_mode == "Manual Selection (Pick Both)":
            pot_pool = [g for g in all_geo_values if g not in test_geos]
            pot_pool_with_pop = []
            label_to_geo_pool = {}
            for geo in pot_pool:
                geo_pop = agg_df[agg_df[geo_col] == geo][POPULATION_COL].sum()
                pop_pct = (geo_pop / total_pop) * 100
                pot_pool_with_pop.append(f"{geo} ({pop_pct:.1f}%)")
                label_to_geo_pool[f"{geo} ({pop_pct:.1f}%)"] = geo
            st.markdown(
                "Select geographies to <span style='color:#15803d;font-weight:600'>include</span> in control group:",
                unsafe_allow_html=True,
            )
            selected_control_labels = st.multiselect(
                "control_geos_manual",
                pot_pool_with_pop,
                on_change=reset_manual_results,
                help="Population percentage of total market shown in brackets. Only geographies not already in the test group are shown.",
                label_visibility="collapsed",
            )
            control_geos = [label_to_geo_pool[label] for label in selected_control_labels]
            st.session_state.user_control_geos = control_geos
            st.session_state.user_selected_mode = True
            force_ctrl_exclude = []
            force_ctrl_include = []
            control_pool_geos = []

        elif setup_mode == "Pick Test, Auto‑Match Controls":
            total_pop = agg_df[POPULATION_COL].sum()
            pot_pool = [g for g in all_geo_values if g not in test_geos]
            pot_pool_with_pop = []
            label_to_geo_pool = {}
            for geo in pot_pool:
                geo_pop = agg_df[agg_df[geo_col] == geo][POPULATION_COL].sum()
                pop_pct = (geo_pop / total_pop) * 100
                pot_pool_with_pop.append(f"{geo} ({pop_pct:.1f}%)")
                label_to_geo_pool[f"{geo} ({pop_pct:.1f}%)"] = geo
            st.markdown(
                "Select geographies to <span style='color:#dc2626;font-weight:600'>exclude</span> from control pool:",
                unsafe_allow_html=True,
            )
            excluded_labels = st.multiselect(
                "exclude_geographies",
                pot_pool_with_pop,
                on_change=reset_results,
                key="exclude_geos_select",
                label_visibility="collapsed",
            )
            excluded_geos = [label_to_geo_pool[label] for label in excluded_labels]
            st.session_state.force_ctrl_exclude = excluded_geos
            control_pool_geos = [g for g in pot_pool if g not in excluded_geos]
            force_ctrl_include = []
            force_ctrl_exclude = []

        else:  # "Set Rules & Auto‑Build Groups"
            total_pop = agg_df[POPULATION_COL].sum()
            # Last run's control-exclude selection — used only to shrink the
            # ctrl_include widget's OPTIONS (a different widget, so this is safe).
            # It must never be subtracted when building ctrl_exclude's own options
            # below, since that would remove a previously-selected exclusion from
            # its own widget's options on this rerun, silently clearing it.
            _force_ctrl_exclude_prev = set(st.session_state.get("force_ctrl_exclude", []))

            def _geo_labels(geos):
                labels, mapping = [], {}
                for geo in geos:
                    geo_pop = agg_df[agg_df[geo_col] == geo][POPULATION_COL].sum()
                    pop_pct = (geo_pop / total_pop) * 100
                    label = f"{geo} ({pop_pct:.1f}%)"
                    labels.append(label)
                    mapping[label] = geo
                return labels, mapping

            # Persisted ctrl_include selections stay selectable even when they now
            # conflict with another rule, so the run's structured conflict blocker
            # (validate_constraints) surfaces the overlap instead of a silent reset.
            _ctrl_include_persisted = {
                label_to_geo[lbl] for lbl in st.session_state.get("ctrl_include_select", [])
            }
            eligible_for_ctrl_include = [
                g
                for g in all_geo_values
                if g in _ctrl_include_persisted
                or (
                    g not in force_exp_include
                    and g not in global_exclude
                    and g not in _force_ctrl_exclude_prev
                )
            ]
            ctrl_options_with_pop, label_to_ctrl_include = _geo_labels(eligible_for_ctrl_include)
            st.markdown(
                "Control geographies to force <span style='color:#15803d;font-weight:600'>include:</span>",
                unsafe_allow_html=True,
            )
            selected_ctrl_include_labels = st.multiselect(
                "ctrl_include",
                ctrl_options_with_pop,
                label_visibility="collapsed",
                help=(
                    "Force-includes the region in the CONTROL candidate pool (it "
                    "cannot be a test region). It is ELIGIBLE for — but not "
                    "guaranteed in — the final control group: the matching "
                    "strategy decides final selection. A region can only be "
                    "force-included in one group."
                ),
                key="ctrl_include_select",
            )
            force_ctrl_include = [
                label_to_ctrl_include[label] for label in selected_ctrl_include_labels
            ]

            _ctrl_exclude_persisted = {
                label_to_geo[lbl] for lbl in st.session_state.get("ctrl_exclude_select", [])
            }
            eligible_for_ctrl_exclude = [
                g
                for g in all_geo_values
                if g in _ctrl_exclude_persisted
                or (
                    g not in force_exp_include
                    and g not in global_exclude
                    and g not in force_ctrl_include
                )
            ]
            exclude_ctrl_options, label_to_ctrl_exclude = _geo_labels(eligible_for_ctrl_exclude)
            st.markdown(
                "Control geographies to force <span style='color:#dc2626;font-weight:600'>exclude:</span>",
                unsafe_allow_html=True,
            )
            selected_ctrl_exclude_labels = st.multiselect(
                "ctrl_exclude",
                exclude_ctrl_options,
                label_visibility="collapsed",
                help=(
                    "Excluded from the CONTROL group only — these regions remain "
                    "available for test selection. To remove a region from the analysis "
                    "entirely, use the 'exclude from both' field above instead."
                ),
                key="ctrl_exclude_select",
            )
            force_ctrl_exclude = [
                label_to_ctrl_exclude[label] for label in selected_ctrl_exclude_labels
            ]
            st.session_state.force_ctrl_exclude = force_ctrl_exclude
            control_pool_geos = [
                g
                for g in all_geo_values
                if g not in force_exp_include
                and g not in global_exclude
                and g not in force_ctrl_exclude
            ]

    if "force_ctrl_exclude" not in st.session_state:
        st.session_state.force_ctrl_exclude = []

    # ------------------------------------------------------------
    # Sidebar strategy parameters (keep in sidebar — do NOT move)
    # ------------------------------------------------------------
    with st.sidebar:
        st.write("---")
        st.header("3. Strategy Parameters")
        force_1to1 = st.checkbox("Force 1-to-1 Match Ratio", value=False)

        if setup_mode == "Manual Selection (Pick Both)":
            max_possible_controls = 0
            min_p, max_p = 0, 0
            st.info(
                "In Manual Selection mode, you select both test and control groups directly. The matching algorithm is bypassed."
            )
        else:
            max_possible_controls = min(len(control_pool_geos), CONFIG["max_control_pool_size"])
            min_p, max_p = 0, 0
            if not force_1to1:
                if max_possible_controls < 2:
                    st.warning("Not enough control geographies available for a pool search.")
                else:
                    default_lower = max(2, int(np.ceil(max_possible_controls / 2)))
                    default_upper = max_possible_controls
                    if default_lower > default_upper:
                        default_lower = default_upper
                    pool_range = st.slider(
                        "Select control group pool size range:",
                        min_value=2,
                        max_value=max_possible_controls,
                        value=(default_lower, default_upper),
                        key=f"pool_slider_{max_possible_controls}",
                        help="The algorithm tests every control group size in this range and selects the one with the best pre-period balance. A wider range is more thorough but slower.",
                    )
                    min_p, max_p = pool_range

        if match_mode == "Stochastic (Genetic Search)":
            genetic_iterations = st.slider(
                "Search iterations",
                min_value=CONFIG["genetic_iterations"]["min"],
                max_value=CONFIG["genetic_iterations"]["max"],
                value=CONFIG["genetic_iterations"]["default"],
                step=100,
                help="Number of random single-swap trials the stochastic search runs per control-group size. Higher values search more combinations but take longer.",
            )
        else:
            genetic_iterations = CONFIG["genetic_iterations"]["default"]

        st.write("---")
        if not st.session_state.get("kpi_pattern_mode"):
            st.header("4. Matching Feature Importance")
            st.caption(f"📊 **{len(active_features)} numeric features** available for weighting")
            if "current_weights" not in st.session_state:
                st.session_state.current_weights = {f: 1 for f in active_features}
            preset_col1, preset_col2 = st.columns(2)
            with preset_col1:
                if st.button("🗑️ Reset All Weights to 1", width="stretch", key="reset_all_weights"):
                    for f in active_features:
                        st.session_state.current_weights[f] = 1
                    st.session_state.w_reset += 1
                    st.rerun()
            with preset_col2:
                if st.button("Reset Slider Positions", width="stretch", key="reset_sliders"):
                    st.session_state.w_reset += 1
                    st.rerun()
            weights = {}
            with st.expander("Demographic Importance Weights", expanded=False):
                search_term = st.text_input(
                    "🔍 Filter features",
                    placeholder="Type to search...",
                    key=f"weight_search_{st.session_state.w_reset}",
                )
                ordered_features = active_features.copy()
                if search_term:
                    ordered_features = [
                        f for f in ordered_features if search_term.lower() in f.lower()
                    ]
                    st.caption(
                        f"Showing {len(ordered_features)} of {len(active_features)} features"
                    )
                container_height = min(500, max(200, len(ordered_features) * 35))
                with st.container(height=container_height):
                    num_columns = 2 if len(ordered_features) > 15 else 1
                    cols = st.columns(num_columns)
                    for idx, f in enumerate(ordered_features):
                        col_idx = idx % num_columns
                        with cols[col_idx]:
                            current_val = st.session_state.current_weights.get(f, 1)
                            display_name = f.replace("_", " ").title() if "_" in f else f
                            if current_val != 1:
                                display_name = f"⭐ {display_name}"
                            weight_val = st.slider(
                                display_name,
                                1,
                                10,
                                current_val,
                                1,
                                key=f"w_{market}_{geography_level}_{f}_{st.session_state.w_reset}",
                                help=f"Weight for {f} (higher = more important for matching)",
                            )
                            st.session_state.current_weights[f] = weight_val
                            weights[f] = weight_val
            for f in active_features:
                if f not in weights:
                    weights[f] = st.session_state.current_weights.get(f, 1)
            non_default_weights = {k: v for k, v in weights.items() if v != 1}
            if non_default_weights:
                with st.expander(
                    f"⚡ Active Overrides ({len(non_default_weights)} features)", expanded=False
                ):
                    for feature, weight in list(non_default_weights.items())[:10]:
                        st.caption(f"**{feature}**: weight = {weight}")
                    if len(non_default_weights) > 10:
                        st.caption(f"... and {len(non_default_weights) - 10} more")
        else:
            # KPI Pattern mode matches on the full weekly shape of each region's own KPI
            # trend — every week contributes equally, so there's no per-feature weighting
            # UI here (unlike Structural mode's demographic weights).
            weights = {f: 1 for f in active_features}

    # ------------------------------------------------------------
    # Run matching
    # ------------------------------------------------------------
    st.markdown(
        "<p class='small-muted'>Tip: start with equal weights, then increase business-critical features if needed.</p>",
        unsafe_allow_html=True,
    )
    run_clicked = st.button("▶ Run Match Analysis", width="stretch", type="primary")

    if run_clicked:
        if not active_features:
            st.error("No numeric matching features were found for this market and geography level.")
            st.stop()

        if setup_mode == "Manual Selection (Pick Both)":
            control_geos = st.session_state.get("user_control_geos", [])
            if len(test_geos) == 0:
                st.error("Please select at least one test geography.")
                st.stop()
            if len(control_geos) == 0:
                st.error("Please select at least one control geography.")
                st.stop()
            overlap = set(test_geos) & set(control_geos)
            if overlap:
                st.error(
                    f"Overlapping geographies: {overlap}. Test and control groups must be disjoint."
                )
                st.stop()

            st.session_state.selected_experiment_regions = list(test_geos)
            st.session_state.test_df = agg_df[agg_df[geo_col].isin(test_geos)].copy()
            st.session_state.final_controls = agg_df[agg_df[geo_col].isin(control_geos)].copy()
            st.session_state.match_mode_res = "User Selected"
            st.session_state.best_n = len(control_geos)
            st.session_state.opt_results = {}
            st.session_state.user_selected_mode = True
            _eligible_df = pd.concat(
                [st.session_state.test_df, st.session_state.final_controls], axis=0
            )
            _eligible_df = impute_missing_features(_eligible_df, active_features)
            _elig_means, _elig_stds = fit_structural_stats(_eligible_df, active_features)
            st.session_state.eligible_means = {f: float(_elig_means[f]) for f in active_features}
            st.session_state.eligible_stds = {f: float(_elig_stds[f]) for f in active_features}

            # ---- Freeze a snapshot of the inputs/outputs used for this run ----
            # so slider changes afterwards don't silently change the displayed results.
            _final_metrics = calculate_metrics(
                st.session_state.test_df,
                st.session_state.final_controls,
                active_features,
                weights,
                st.session_state.eligible_means,
                st.session_state.eligible_stds,
            )
            _eligible_market_pop = agg_df[POPULATION_COL].sum()
            _experiment_pop = agg_df[agg_df[geo_col].isin(test_geos)][POPULATION_COL].sum()
            _control_pop = agg_df[agg_df[geo_col].isin(control_geos)][POPULATION_COL].sum()
            _test_pop_pct = (
                (_experiment_pop / _eligible_market_pop) * 100 if _eligible_market_pop > 0 else 0
            )
            _control_pop_pct = (
                (_control_pop / _eligible_market_pop) * 100 if _eligible_market_pop > 0 else 0
            )
            st.session_state.match_run_snapshot = {
                "market": market,
                "geography_level": geography_level,
                "geo_col": geo_col,
                "setup_mode": setup_mode,
                "match_mode": "User Selected",
                "matching_method": st.session_state.get("matching_method_sidebar"),
                "test_geos": list(test_geos),
                "selected_controls": sorted(
                    st.session_state.final_controls[geo_col].dropna().astype(str).tolist()
                ),
                "control_pool_geos": [],
                "global_exclusions": sorted(global_exclude),
                "test_only_exclusions": sorted(force_exp_exclude),
                "control_only_exclusions": sorted(force_ctrl_exclude),
                "forced_test_regions": sorted(force_exp_include),
                "forced_control_eligibility": sorted(force_ctrl_include),
                "guided_seed": None,
                "target_test_share": target_test_share,
                "target_tolerance_pp": target_tolerance_pp,
                "test_share": float(_test_pop_pct),
                "kpi_pattern_period_quality": st.session_state.get("kpi_pattern_period_quality"),
                "kpi_pattern_metric": st.session_state.get("kpi_pattern_metric_value_sidebar"),
                "kpi_pattern_agg_col": st.session_state.get("kpi_pattern_agg_col_sidebar"),
                "kpi_pattern_date_range": st.session_state.get("kpi_pattern_date_range"),
                "active_features": list(active_features),
                "weights": dict(weights),
                "eligible_means": tuple(
                    st.session_state.eligible_means.get(f, np.nan) for f in active_features
                ),
                "eligible_stds": tuple(
                    st.session_state.eligible_stds.get(f, np.nan) for f in active_features
                ),
                "best_n": len(control_geos),
            }
            st.session_state.match_run_metrics = {
                "weighted_structural_distance": _final_metrics["weighted_structural_distance"],
                "mean_abs_smd": _final_metrics["mean_abs_smd"],
                "smd_list": _final_metrics["smd_list"],
                "test_means": _final_metrics["test_means"],
                "control_means": _final_metrics["control_means"],
                "raw_diffs": _final_metrics.get("raw_diffs"),
                "weighted_contributions": _final_metrics.get("weighted_contributions"),
                "test_population_share": _test_pop_pct,
                "control_population_share": _control_pop_pct,
                "control_group_size": len(control_geos),
            }
            st.session_state.match_results_stale = False
            _stamp_match_quality()
            _clear_production_power_state()

            cleanup_session_state()
            st.success(
                f"Groups set. Test: {len(test_geos)} regions, Control: {len(control_geos)} regions."
            )

        else:
            if setup_mode == "Set Rules & Auto‑Build Groups":
                constraints = MatchConstraints(
                    exclude_from_both=tuple(global_exclude),
                    force_test_include=tuple(force_exp_include),
                    test_only_exclude=tuple(force_exp_exclude),
                    force_control_include=tuple(force_ctrl_include),
                    control_only_exclude=tuple(force_ctrl_exclude),
                )
                # Structured overlap validation — the single authority for
                # constraint conflicts (widget option subtraction is only a
                # convenience, never the only prevention mechanism). Every
                # overlap is reported as a visible structured blocker.
                constraint_conflicts = validate_constraints(constraints)
                if constraint_conflicts:
                    for _conflict in constraint_conflicts:
                        st.error(
                            f"🚫 Invalid constraints: **{_conflict.region}** is assigned to "
                            f"multiple constraint fields: {', '.join(_conflict.fields)}. "
                            "A region can only be assigned to one rule — remove the "
                            "overlapping assignment before running."
                        )
                    st.stop()
                global_exclude_set = set(global_exclude)
                excluded_from_test = set(force_exp_exclude) | global_exclude_set
                excluded_from_control = set(force_ctrl_exclude) | global_exclude_set
                _guided_rng = np.random.default_rng(GUIDED_SEARCH_CONFIG.seed)
                test_geos, achieved_share, target_met = find_guided_test_group(
                    agg_df,
                    geo_col,
                    total_market_pop,
                    force_exp_include,
                    list(excluded_from_test),
                    force_ctrl_include,
                    list(excluded_from_control),
                    target_test_share,
                    target_tolerance_pp,
                    guided_iterations,
                    rng=_guided_rng,
                )
                if len(test_geos) == 0:
                    st.error(
                        "Could not construct a valid test group with the provided constraints."
                    )
                    st.stop()
                if not target_met:
                    st.warning(
                        kpi_share_label(
                            f"Target population share range was not met. Closest achieved: "
                            f"{format_percentage(achieved_share * 100)} "
                            f"(target {format_percentage(target_test_share)}, ±{target_tolerance_pp}pp)."
                        )
                    )
                st.session_state.guided_share_info = {
                    "achieved": achieved_share * 100,
                    "target": target_test_share,
                    "tolerance": target_tolerance_pp,
                    "met": target_met,
                }
                all_geos = set(agg_df[geo_col].unique())
                # Note: force_exp_exclude is deliberately NOT subtracted here — a region
                # excluded from the test group remains available as a control. Exclusions
                # are one-sided unless a region appears in BOTH exclusion lists, or in
                # global_exclude, which removes it from the analysis entirely.
                control_pool_geos = sorted(
                    (all_geos - set(test_geos) - excluded_from_control) | set(force_ctrl_include)
                )
            else:
                st.session_state.guided_share_info = None
                if "control_pool_geos" not in locals():
                    control_pool_geos = [
                        g
                        for g in all_geo_values
                        if g not in test_geos
                        and g not in st.session_state.get("force_ctrl_exclude", [])
                    ]

            if len(test_geos) == 0:
                st.error(
                    "No test regions selected. Please select at least one test region before running."
                )
                st.stop()
            st.session_state.selected_experiment_regions = list(test_geos)
            test_df_run = agg_df[agg_df[geo_col].isin(test_geos)].copy()
            pool_df = agg_df[agg_df[geo_col].isin(control_pool_geos)].copy()
            test_df_run = impute_missing_features(test_df_run, active_features)
            pool_df = impute_missing_features(pool_df, active_features)

            if force_1to1:
                s_min = s_max = len(test_geos)
            else:
                s_min, s_max = min_p, max_p
                if s_min <= 0 or s_max <= 0:
                    st.error(
                        "Invalid control pool size range. Please ensure min size >= 2 and max size > 0."
                    )
                    st.stop()
            if len(pool_df) < s_max:
                st.error(f"Insufficient controls available. Need {s_max}, have {len(pool_df)}.")
                st.stop()

            eligible_df = pd.concat([test_df_run, pool_df], axis=0)
            eligible_df = impute_missing_features(eligible_df, active_features)
            eligible_means, eligible_stds = fit_structural_stats(eligible_df, active_features)
            eligible_means_tuple = tuple(float(eligible_means[f]) for f in active_features)
            eligible_stds_tuple = tuple(float(eligible_stds[f]) for f in active_features)
            st.session_state.eligible_means = dict(zip(active_features, eligible_means_tuple))
            st.session_state.eligible_stds = dict(zip(active_features, eligible_stds_tuple))

            w_vec, p_scaled, t_cent = preprocess_data(
                pool_df,
                test_df_run,
                active_features,
                weights,
                eligible_means_tuple,
                eligible_stds_tuple,
            )
            # One vectorised scorer for the whole run — the strategy loops below score
            # hundreds to thousands of candidate groups against the same fixed pool.
            fast_metrics = make_fast_metrics_fn(
                pool_df, test_df_run, active_features, weights, eligible_means, eligible_stds
            )
            opt_data = []
            best_score = float("inf")
            best_idx = None
            global_conv = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            size_range = [len(test_geos)] if force_1to1 else range(s_min, s_max + 1)
            total_iterations = len(size_range)

            for i, n in enumerate(size_range):
                status_text.text(
                    f"Testing {n} controls..." if not force_1to1 else "Finding best 1-to-1 match..."
                )
                if match_mode == "Greedy (Nearest Neighbor)":
                    c_idx, metrics = basic_strategy(pool_df, p_scaled, t_cent, n, fast_metrics)
                    mean_abs_smd = metrics["mean_abs_smd"]
                    # Use weighted structural distance as the optimisation objective so slider weights affect control selection.
                    # Mean Abs SMD is retained as an unweighted diagnostic balance metric.
                    optimisation_score = metrics["weighted_structural_distance"]
                    opt_data.append(
                        {
                            "Num_Controls": n,
                            "Weighted_Structural_Distance": metrics["weighted_structural_distance"],
                            "Mean_Abs_SMD": mean_abs_smd,
                            "Optimisation_Score": optimisation_score,
                            "Indices": c_idx,
                        }
                    )
                    if optimisation_score < best_score:
                        best_score, best_idx = optimisation_score, c_idx
                elif match_mode == "Refined Greedy (Hill Climbing)":
                    curr_idx, metrics, conv = intermediate_strategy(
                        pool_df,
                        p_scaled,
                        t_cent,
                        n,
                        fast_metrics,
                        CONFIG["max_hill_climbing_swaps"],
                    )
                    curr_score = metrics["weighted_structural_distance"]
                    curr_mean_abs_smd = metrics["mean_abs_smd"]
                    optimisation_score = curr_score
                    opt_data.append(
                        {
                            "Num_Controls": n,
                            "Weighted_Structural_Distance": curr_score,
                            "Mean_Abs_SMD": curr_mean_abs_smd,
                            "Optimisation_Score": optimisation_score,
                            "Indices": curr_idx,
                        }
                    )
                    if optimisation_score < best_score:
                        best_score, best_idx, global_conv = optimisation_score, curr_idx, conv
                elif match_mode == "Stochastic (Genetic Search)":
                    # Start from a good nearest-neighbour candidate group, then randomly swap one
                    # selected control for one unselected control, keeping improving swaps.
                    # Weighted Structural Distance is the optimisation objective; Mean Abs SMD is diagnostic only.
                    nn_start_idx = nearest_neighbor_start(pool_df, p_scaled, t_cent, n)
                    best_idx_for_n, best_metrics_for_n, evaluated_count, conv = (
                        stochastic_genetic_search(
                            pool_df,
                            test_df_run,
                            active_features,
                            weights,
                            n,
                            calculate_metrics,
                            eligible_means,
                            eligible_stds,
                            nn_start_idx=nn_start_idx,
                            n_iterations=genetic_iterations,
                            random_state=42,
                            fast_metrics_fn=fast_metrics,
                        )
                    )
                    optimisation_score = best_metrics_for_n["weighted_structural_distance"]
                    opt_data.append(
                        {
                            "Num_Controls": n,
                            "Weighted_Structural_Distance": best_metrics_for_n[
                                "weighted_structural_distance"
                            ],
                            "Mean_Abs_SMD": best_metrics_for_n["mean_abs_smd"],
                            "Optimisation_Score": optimisation_score,
                            "Indices": best_idx_for_n,
                            "Candidates_Evaluated": evaluated_count,
                        }
                    )
                    if optimisation_score < best_score:
                        best_score = optimisation_score
                        best_idx = best_idx_for_n
                        global_conv = conv
                progress_bar.progress((i + 1) / total_iterations)

            progress_bar.empty()
            status_text.empty()
            st.session_state.final_controls = agg_df.loc[best_idx].copy()
            st.session_state.opt_results = {
                "size_df": pd.DataFrame(opt_data),
                "convergence": global_conv,
            }
            st.session_state.best_n = len(best_idx)
            st.session_state.test_df = test_df_run.copy()
            st.session_state.match_mode_res = match_mode

            # ---- Freeze a snapshot of the inputs/outputs used for this run ----
            # so slider changes afterwards don't silently change the displayed results.
            final_metrics = calculate_metrics(
                test_df_run,
                agg_df.loc[best_idx],
                active_features,
                weights,
                eligible_means,
                eligible_stds,
            )
            _eligible_market_pop = agg_df[POPULATION_COL].sum()
            _experiment_pop = agg_df[agg_df[geo_col].isin(test_geos)][POPULATION_COL].sum()
            _control_pop = agg_df[
                agg_df[geo_col].isin(st.session_state.final_controls[geo_col].tolist())
            ][POPULATION_COL].sum()
            _test_pop_pct = (
                (_experiment_pop / _eligible_market_pop) * 100 if _eligible_market_pop > 0 else 0
            )
            _control_pop_pct = (
                (_control_pop / _eligible_market_pop) * 100 if _eligible_market_pop > 0 else 0
            )
            st.session_state.match_run_snapshot = {
                "market": market,
                "geography_level": geography_level,
                "geo_col": geo_col,
                "setup_mode": setup_mode,
                "match_mode": match_mode,
                "matching_method": st.session_state.get("matching_method_sidebar"),
                "test_geos": list(test_geos),
                "selected_controls": sorted(
                    st.session_state.final_controls[geo_col].dropna().astype(str).tolist()
                ),
                "control_pool_geos": list(control_pool_geos)
                if "control_pool_geos" in locals()
                else [],
                "global_exclusions": sorted(global_exclude),
                "test_only_exclusions": sorted(force_exp_exclude),
                # The executed control-pool exclusions: in 'Pick Test,
                # Auto-Match Controls' they live in excluded_geos (the local
                # force_ctrl_exclude is reset to [] there), in 'Set Rules &
                # Auto-Build Groups' they live in force_ctrl_exclude.
                "control_only_exclusions": sorted(
                    excluded_geos if "excluded_geos" in locals() else force_ctrl_exclude
                ),
                "forced_test_regions": sorted(force_exp_include),
                "forced_control_eligibility": sorted(force_ctrl_include),
                "guided_seed": GUIDED_SEARCH_CONFIG.seed,
                "target_test_share": target_test_share,
                "target_tolerance_pp": target_tolerance_pp,
                "test_share": float(_test_pop_pct),
                "kpi_pattern_period_quality": st.session_state.get("kpi_pattern_period_quality"),
                "kpi_pattern_metric": st.session_state.get("kpi_pattern_metric_value_sidebar"),
                "kpi_pattern_agg_col": st.session_state.get("kpi_pattern_agg_col_sidebar"),
                "kpi_pattern_date_range": st.session_state.get("kpi_pattern_date_range"),
                "active_features": list(active_features),
                "weights": dict(weights),
                "eligible_means": tuple(eligible_means_tuple)
                if "eligible_means_tuple" in locals()
                else None,
                "eligible_stds": tuple(eligible_stds_tuple)
                if "eligible_stds_tuple" in locals()
                else None,
                "best_n": len(best_idx) if best_idx is not None else None,
            }
            st.session_state.match_run_metrics = {
                "weighted_structural_distance": final_metrics["weighted_structural_distance"],
                "mean_abs_smd": final_metrics["mean_abs_smd"],
                "smd_list": final_metrics["smd_list"],
                "test_means": final_metrics["test_means"],
                "control_means": final_metrics["control_means"],
                "raw_diffs": final_metrics.get("raw_diffs"),
                "weighted_contributions": final_metrics.get("weighted_contributions"),
                "test_population_share": _test_pop_pct,
                "control_population_share": _control_pop_pct,
                "control_group_size": len(best_idx),
            }
            st.session_state.match_results_stale = False
            _stamp_match_quality()

            cleanup_session_state()
            st.success(
                f"Match completed. Selected {len(best_idx)} controls with "
                f"Weighted Structural Distance = {best_score:.4f}."
            )

    # ------------------------------------------------------------
    # Results display (Summary, Diagnostics, Export)
    # ------------------------------------------------------------
    if run_clicked and len(test_geos) == 0:
        st.warning("Select at least one test region before running analysis.")

    if st.session_state.final_controls is not None:
        # ---- Read from the FROZEN snapshot of the last completed run ----
        # Do not recalculate display metrics from the current live slider weights here;
        # the cards/table/chart below must only change when Run Match Analysis is clicked again.
        run_metrics = st.session_state.get("match_run_metrics", {})
        run_snapshot = st.session_state.get("match_run_snapshot", {})
        run_weights = run_snapshot.get("weights", {})
        run_features = run_snapshot.get("active_features", active_features)

        if not run_metrics or not run_snapshot:
            # Safety net for any legacy session state saved before this snapshot pattern existed.
            if not st.session_state.get("eligible_means") or not st.session_state.get(
                "eligible_stds"
            ):
                _fallback_df = pd.concat(
                    [st.session_state.test_df, st.session_state.final_controls], axis=0
                )
                _fallback_df = impute_missing_features(_fallback_df, active_features)
                _fb_means, _fb_stds = fit_structural_stats(_fallback_df, active_features)
                st.session_state.eligible_means = {f: float(_fb_means[f]) for f in active_features}
                st.session_state.eligible_stds = {f: float(_fb_stds[f]) for f in active_features}
            _em_tuple = tuple(
                st.session_state.eligible_means.get(f, np.nan) for f in active_features
            )
            _es_tuple = tuple(
                st.session_state.eligible_stds.get(f, np.nan) for f in active_features
            )
            _fallback_metrics = calculate_metrics_cached(
                st.session_state.test_df,
                st.session_state.final_controls,
                tuple(active_features),
                tuple(weights.get(f, 1.0) for f in active_features),
                _em_tuple,
                _es_tuple,
            )
            run_metrics = {
                "weighted_structural_distance": _fallback_metrics["weighted_structural_distance"],
                "mean_abs_smd": _fallback_metrics["mean_abs_smd"],
                "smd_list": _fallback_metrics["smd_list"],
                "test_means": _fallback_metrics["test_means"],
                "control_means": _fallback_metrics["control_means"],
                "raw_diffs": _fallback_metrics.get("raw_diffs"),
                "weighted_contributions": _fallback_metrics.get("weighted_contributions"),
                "control_group_size": len(st.session_state.final_controls),
            }
            run_weights = weights
            run_features = active_features

        mean_abs_smd = run_metrics["mean_abs_smd"]
        weighted_structural_distance = run_metrics["weighted_structural_distance"]
        smd_list = run_metrics["smd_list"]
        e_m = run_metrics["test_means"]
        c_m = run_metrics["control_means"]
        weighted_contributions = run_metrics["weighted_contributions"]
        st.subheader("🔍 MATCHING RESULTS")

        setup_changed = matching_setup_changed_since_last_run(
            run_snapshot, market, geography_level, match_mode, test_geos, weights
        )
        if setup_changed:
            st.info(
                "You have changed the matching setup since the last run. "
                "The results below still show the last completed match. Click Run Match Analysis to update them."
            )

        raw_diffs = run_metrics.get("raw_diffs")
        if raw_diffs is None:
            raw_diffs = [round(e - c, 4) for e, c in zip(e_m, c_m)]
        comp_df = pd.DataFrame(
            {
                "Feature": run_features[: len(smd_list)],
                "Weight": [run_weights.get(f, 1.0) for f in run_features[: len(smd_list)]],
                "Test Mean": [round(x, 4) for x in e_m[: len(smd_list)]],
                "Ctrl Mean": [round(x, 4) for x in c_m[: len(smd_list)]],
                "Raw Diff": [round(x, 4) for x in raw_diffs[: len(smd_list)]],
                "Abs SMD": [round(x, 4) if np.isfinite(x) else np.nan for x in smd_list],
                "Weighted Contribution": [
                    round(x, 4) for x in weighted_contributions[: len(smd_list)]
                ],
            }
        ).sort_values("Abs SMD", ascending=False)

        tab_choice = st.radio(
            "Select View",
            ["📊 Summary", "📈 Diagnostics", "💾 Export"],
            horizontal=True,
            key="tab_selector_main",
            label_visibility="collapsed",
        )

        if tab_choice == "📊 Summary":
            experiment_pop_pct = run_metrics.get("test_population_share")
            control_pop_pct = run_metrics.get("control_population_share")
            if experiment_pop_pct is None or control_pop_pct is None:
                # Safety net: derive from the frozen test_df/final_controls (not live weights)
                eligible_market_pop = agg_df[POPULATION_COL].sum()
                selected_experiment_regions = (
                    st.session_state.selected_experiment_regions
                    or st.session_state.test_df[geo_col].tolist()
                )
                selected_control_regions = st.session_state.final_controls[geo_col].tolist()
                experiment_pop = agg_df[agg_df[geo_col].isin(selected_experiment_regions)][
                    POPULATION_COL
                ].sum()
                control_pop = agg_df[agg_df[geo_col].isin(selected_control_regions)][
                    POPULATION_COL
                ].sum()
                experiment_pop_pct = (
                    (experiment_pop / eligible_market_pop) * 100 if eligible_market_pop > 0 else 0
                )
                control_pop_pct = (
                    (control_pop / eligible_market_pop) * 100 if eligible_market_pop > 0 else 0
                )
            control_group_size = run_metrics.get(
                "control_group_size", len(st.session_state.final_controls)
            )

            ck1, ck2, ck3, ck4, ck5 = st.columns(5)
            with ck1:
                st.metric(
                    "Weighted Structural Distance",
                    round(weighted_structural_distance, 4),
                    help="Weighted Euclidean distance between standardised test and control feature means, using the slider weights at the time of the last run. This is the optimisation objective. Lower is better — 0 means identical means across all features.",
                )
            with ck2:
                smd_color = (
                    "🟢"
                    if mean_abs_smd < SMD_GOOD_THRESHOLD
                    else "🟡"
                    if mean_abs_smd < SMD_HIGH_THRESHOLD
                    else "🔴"
                )
                st.metric(
                    "Mean Abs SMD",
                    f"{smd_color} {round(mean_abs_smd, 4)}",
                    help=f"Average absolute Standardised Mean Difference across all features (unweighted, diagnostic only). 🟢 < {SMD_GOOD_THRESHOLD:.2f} = good balance, 🟡 {SMD_GOOD_THRESHOLD:.2f}–{SMD_HIGH_THRESHOLD:.2f} = moderate imbalance, 🔴 ≥ {SMD_HIGH_THRESHOLD:.2f} = high imbalance.",
                )
            with ck3:
                st.metric(
                    "Control Group Size",
                    control_group_size,
                    help="Number of control regions selected in the last completed run.",
                )
            with ck4:
                st.metric(
                    kpi_share_label("Test Population Share"),
                    format_percentage(experiment_pop_pct),
                    help=kpi_share_label(
                        "Percentage of total market population covered by the test regions used in the last completed run."
                    ),
                )
                if st.session_state.guided_share_info:
                    st.caption(
                        f"Target: {format_percentage(st.session_state.guided_share_info['target'])}"
                    )
            with ck5:
                st.metric(
                    kpi_share_label("Control Population Share"),
                    format_percentage(control_pop_pct),
                    help=kpi_share_label(
                        "Percentage of total market population covered by the control regions selected in the last completed run."
                    ),
                )
            st.caption(
                "Weighted Structural Distance is the optimisation objective and uses the slider weights from the last completed run. Mean Abs SMD is an unweighted diagnostic balance check. These results are frozen until you click Run Match Analysis again."
            )

            with st.expander("View Selected Groups", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    st.write("**Test Geographies**")
                    st.table(
                        pd.DataFrame({"Test Geography": st.session_state.test_df[geo_col].values})
                    )
                with c2:
                    st.write("**Control Geographies**")
                    st.table(
                        pd.DataFrame(
                            {"Control Geography": st.session_state.final_controls[geo_col].values}
                        )
                    )

            st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
            cl, cr = st.columns([1.5, 1])
            with cl:
                st.write("**Feature Comparison Table**")

                def color_smd(val):
                    if pd.isna(val):
                        return "background-color: #e5e7eb"
                    if val < SMD_GOOD_THRESHOLD:
                        return "background-color: #c6efce"
                    elif val < SMD_HIGH_THRESHOLD:
                        return "background-color: #ffeb9c"
                    else:
                        return "background-color: #ffc7ce"

                display_comp = comp_df.copy()
                if st.session_state.get("kpi_pattern_mode"):
                    display_comp["Feature"] = display_comp["Feature"].apply(kpi_feature_date_label)
                for c in ["Test Mean", "Ctrl Mean", "Raw Diff"]:
                    display_comp[c] = display_comp[c].astype(object)
                prop_features = set(proportion_cols)
                for idx, row in display_comp.iterrows():
                    feat = row["Feature"]
                    if feat in prop_features:
                        display_comp.at[idx, "Test Mean"] = f"{row['Test Mean'] * 100:.1f}%"
                        display_comp.at[idx, "Ctrl Mean"] = f"{row['Ctrl Mean'] * 100:.1f}%"
                        display_comp.at[idx, "Raw Diff"] = f"{row['Raw Diff'] * 100:.1f}%"
                    elif feat in [POPULATION_COL, "Population Density"]:
                        display_comp.at[idx, "Test Mean"] = f"{row['Test Mean']:,.1f}"
                        display_comp.at[idx, "Ctrl Mean"] = f"{row['Ctrl Mean']:,.1f}"
                        display_comp.at[idx, "Raw Diff"] = f"{row['Raw Diff']:,.1f}"
                    else:
                        display_comp.at[idx, "Test Mean"] = f"{row['Test Mean']:.4f}"
                        display_comp.at[idx, "Ctrl Mean"] = f"{row['Ctrl Mean']:.4f}"
                        display_comp.at[idx, "Raw Diff"] = f"{row['Raw Diff']:.4f}"
                styled_comp = display_comp.style.map(color_smd, subset=["Abs SMD"]).format(
                    {"Weight": "{:.0f}", "Abs SMD": "{:.4f}"}, na_rep=""
                )
                st.dataframe(styled_comp, width="stretch", hide_index=False, height=400)
                st.caption(
                    "Abs SMD is unweighted and shows the actual balance for each feature. The slider weight changes how much that feature influences control selection (via Weighted Contribution), but it does not change the SMD formula itself."
                )
            with cr:
                st.write("**Balance (Love Plot)**")
                pdf = comp_df.sort_values("Abs SMD")
                if st.session_state.get("kpi_pattern_mode"):
                    pdf = pdf.copy()
                    pdf["Feature"] = pdf["Feature"].apply(kpi_feature_date_label)
                fig = px.scatter(
                    pdf,
                    x="Abs SMD",
                    y="Feature",
                    color="Abs SMD",
                    color_continuous_scale=["#CCFBF1", "#0F766E"],
                    title="Feature Balance Plot",
                    labels={"Abs SMD": "Absolute SMD"},
                )
                fig.add_vline(x=SMD_GOOD_THRESHOLD, line_dash="dash", line_color="#0F766E")
                fig.add_vline(x=SMD_HIGH_THRESHOLD, line_dash="dash", line_color="#F59E0B")
                fig.update_layout(
                    height=500,
                    margin=dict(l=10, r=10, t=50, b=10),
                    paper_bgcolor="white",
                    plot_bgcolor="white",
                )
                st.plotly_chart(fig, width="stretch")

        elif tab_choice == "📈 Diagnostics":
            st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
            if (
                not force_1to1
                and len(st.session_state.opt_results.get("size_df", pd.DataFrame())) > 0
            ):
                st.subheader(
                    "Pool Size Optimization",
                    help="This chart tests different control group sizes to find the best balance. The dashed line marks the size that resulted in the lowest SMD.",
                )
                size_df = st.session_state.opt_results["size_df"]
                required_cols = ["Num_Controls", "Weighted_Structural_Distance", "Mean_Abs_SMD"]
                missing_cols = [c for c in required_cols if c not in size_df.columns]
                if missing_cols:
                    st.error(
                        f"Pool size results are missing expected columns: {missing_cols}. Check that all match-mode branches write the same opt_data keys."
                    )
                else:
                    chart_df = size_df[required_cols]
                    rule_df = pd.DataFrame({"best_n": [st.session_state.best_n]})
                    base = (
                        alt.Chart(chart_df)
                        .mark_line(point=True, color="#7C3AED")
                        .encode(
                            x=alt.X("Num_Controls:Q", title="Number of Controls"),
                            y=alt.Y(
                                "Weighted_Structural_Distance:Q",
                                title="Weighted Structural Distance",
                            ),
                            tooltip=[
                                "Num_Controls",
                                "Weighted_Structural_Distance",
                                "Mean_Abs_SMD",
                            ],
                        )
                    )
                    marker = (
                        alt.Chart(rule_df)
                        .mark_rule(color="#0F766E", strokeDash=[6, 4])
                        .encode(x="best_n:Q")
                    )
                    st.altair_chart((base + marker).properties(height=280), width="stretch")
                    st.caption(
                        "Lower is better. This is the slider-weighted objective used to select the control group. Mean Abs SMD is retained as an unweighted balance diagnostic."
                    )
            if (
                st.session_state.match_mode_res != "Greedy (Nearest Neighbor)"
                and st.session_state.opt_results.get("convergence")
            ):
                st.subheader(
                    "Search Convergence",
                    help="This shows whether the search improved as it tried alternative control combinations.",
                )
                conv_df = pd.DataFrame(
                    {
                        "step": list(range(len(st.session_state.opt_results["convergence"]))),
                        "Weighted_Structural_Distance": st.session_state.opt_results["convergence"],
                    }
                )
                conv_chart = (
                    alt.Chart(conv_df)
                    .mark_line(color="#0F766E")
                    .encode(
                        x=alt.X("step:Q", title="Improvement Steps"),
                        y=alt.Y(
                            "Weighted_Structural_Distance:Q", title="Weighted Structural Distance"
                        ),
                        tooltip=["step", "Weighted_Structural_Distance"],
                    )
                    .properties(
                        height=280, title=f"Optimization Path for N={st.session_state.best_n}"
                    )
                )
                st.altair_chart(conv_chart, width="stretch")
            st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
            st.subheader(
                "Feature Distribution Detail",
                help="Compare spread, median, and outliers of selected feature values for Test vs Control.",
            )
            display_features_for_viz = active_features[: min(len(active_features), 20)]
            if display_features_for_viz:
                if "selected_viz_feature" not in st.session_state:
                    st.session_state.selected_viz_feature = display_features_for_viz[0]
                viz_f = st.selectbox(
                    "Select feature to view density distribution:",
                    display_features_for_viz,
                    index=display_features_for_viz.index(st.session_state.selected_viz_feature)
                    if st.session_state.selected_viz_feature in display_features_for_viz
                    else 0,
                    key="feature_distribution_select",
                )
                st.session_state.selected_viz_feature = viz_f
                if (
                    viz_f in st.session_state.test_df.columns
                    and viz_f in st.session_state.final_controls.columns
                ):
                    test_data = st.session_state.test_df[viz_f].dropna()
                    control_data = st.session_state.final_controls[viz_f].dropna()
                    if len(test_data) > 1 and len(control_data) > 1:
                        density_df = pd.concat(
                            [
                                pd.DataFrame({"value": test_data, "Group": "Test"}),
                                pd.DataFrame({"value": control_data, "Group": "Control"}),
                            ],
                            ignore_index=True,
                        )
                        fig_dist = px.violin(
                            density_df,
                            x="Group",
                            y="value",
                            color="Group",
                            box=True,
                            points="all",
                            color_discrete_map={"Test": "#7C3AED", "Control": "#0F766E"},
                            labels={"value": viz_f},
                        )
                        fig_dist.update_layout(
                            title=f"Distribution Comparison: {viz_f}",
                            yaxis_title=viz_f,
                            xaxis_title="Group",
                            showlegend=False,
                            height=420,
                            margin=dict(l=10, r=10, t=50, b=10),
                        )
                        st.plotly_chart(fig_dist, width="stretch")
                    else:
                        st.warning(
                            "Insufficient data points for distribution plot. Need at least 2 points per group."
                        )
            else:
                st.info("No numeric features available for diagnostics.")

        elif tab_choice == "💾 Export":
            st.markdown('<div class="custom-divider"></div>', unsafe_allow_html=True)
            _kpi_export_mode = st.session_state.get("kpi_pattern_mode", False)
            if _kpi_export_mode:
                with st.expander("📋 What will be exported?", expanded=True):
                    st.markdown(f"""
                    The export lists every **{geo_col}** with its test/control assignment:

                    - **{geo_col}** — the aggregation level used for matching
                    - **Test Geography** — Yes if assigned to the test group
                    - **Control Geography** — Yes if assigned to the control group
                    """)
            else:
                with st.expander("📋 What will be exported?", expanded=True):
                    st.markdown(f"""
                    The export lists every Adobe geography with its **{geo_col}** grouping and test/control assignment:

                    - **Market** — {market}
                    - **Adobe Reference List** — every geography as it appears in Adobe
                    - **{geo_col}** — the aggregation level used for matching
                    - **Test Geography** — Yes if assigned to the test group
                    - **Control Geography** — Yes if assigned to the control group
                    """)
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📥 Export to Excel", width="stretch", type="primary"):
                    try:
                        _test_geos = set(
                            st.session_state.test_df[geo_col].astype(str).str.strip().tolist()
                        )
                        _ctrl_geos = set(
                            st.session_state.final_controls[geo_col]
                            .astype(str)
                            .str.strip()
                            .tolist()
                        )

                        if _kpi_export_mode:
                            # No Adobe reference sheet exists in KPI Pattern mode — build the
                            # lookup directly from the aggregation-level values used for matching.
                            _lookup = pd.DataFrame(
                                {geo_col: sorted(agg_df[geo_col].astype(str).str.strip().unique())}
                            )
                            _lookup["Test Geography"] = _lookup[geo_col].apply(
                                lambda g: "Yes" if g in _test_geos else ""
                            )
                            _lookup["Control Geography"] = _lookup[geo_col].apply(
                                lambda g: "Yes" if g in _ctrl_geos else ""
                            )
                            _lookup = _lookup.sort_values(geo_col).reset_index(drop=True)
                        else:
                            _raw = market_df_raw.copy()

                            # Pull just Adobe reference + selected geo_col
                            _keep = [c for c in [ADOBE_COL, geo_col] if c in _raw.columns]
                            _lookup = _raw[_keep].drop_duplicates().copy()
                            for c in _keep:
                                _lookup[c] = _lookup[c].astype(str).str.strip()

                            _lookup.insert(0, "Market", market)
                            _lookup["Test Geography"] = _lookup[geo_col].apply(
                                lambda g: "Yes" if g in _test_geos else ""
                            )
                            _lookup["Control Geography"] = _lookup[geo_col].apply(
                                lambda g: "Yes" if g in _ctrl_geos else ""
                            )

                            if ADOBE_COL in _lookup.columns:
                                _lookup = _lookup.sort_values(ADOBE_COL).reset_index(drop=True)

                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine="openpyxl") as writer:
                            _lookup.to_excel(writer, sheet_name="Geo_Assignments", index=False)
                            ws = writer.sheets["Geo_Assignments"]
                            for col_cells in ws.columns:
                                max_len = max(
                                    (len(str(c.value)) for c in col_cells if c.value), default=10
                                )
                                ws.column_dimensions[col_cells[0].column_letter].width = min(
                                    max_len + 4, 60
                                )

                        _n_test = _lookup["Test Geography"].eq("Yes").sum()
                        _n_ctrl = _lookup["Control Geography"].eq("Yes").sum()
                        st.download_button(
                            label="Download Excel",
                            data=output.getvalue(),
                            file_name=f"geo_assignments_{market}_{geography_level}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                        st.success(
                            f"✅ Export ready — {len(_lookup)} geographies, {_n_test} test, {_n_ctrl} control."
                        )
                    except Exception as e:
                        st.error(
                            "We couldn't create the Excel export. Please try again, and check that a valid control group has been selected."
                        )
                        with st.expander("Technical details"):
                            st.code(f"{type(e).__name__}: {e}")
            with col2:
                if st.button("📋 Copy Summary to Clipboard", width="stretch"):
                    _summary_test_share_pct = experiment_pop / eligible_market_pop * 100
                    _summary_control_share_pct = control_pop / eligible_market_pop * 100
                    _guided_seed_line = (
                        f"\nGuided Search Seed: {GUIDED_SEARCH_CONFIG.seed}"
                        if setup_mode == "Set Rules & Auto-Build Groups"
                        else ""
                    )
                    summary_text = f"""GEO-MATCH RESULTS SUMMARY\n=========================\nMarket: {market}\nGeography Level: {geography_level}\nStrategy: {match_mode}{_guided_seed_line}\n----------------------------------------\nMean Abs SMD (unweighted diagnostic): {mean_abs_smd:.4f}\nWeighted Structural Distance (optimisation objective): {weighted_structural_distance:.4f}\nControl Group Size: {len(st.session_state.final_controls)}\nTest Group Size: {len(st.session_state.test_df)}\n{kpi_share_label("Test Population Share")}: {format_percentage(_summary_test_share_pct)}\n{kpi_share_label("Control Population Share")}: {format_percentage(_summary_control_share_pct)}"""
                    st.code(summary_text, language="text")
                    st.caption("Copy the text above manually")


# =============================================================================
# TAB 1: MATCHING SETUP
# =============================================================================
with tab1:
    render_structural_matching_tab()

# =============================================================================
# TAB 2: DESIGN FUTURE GEO TEST
# TAB 3: EVALUATE COMPLETED GEO TEST
# =============================================================================


def render_method_comparison_table(results, mode, test_start, control_regions_val):
    """
    Renders the Method Comparison table (traffic-light diagnostics per method),
    its captions, and the "How to interpret these results" expander.

    Extracted from render_time_series_validation() as a self-contained rendering
    step: it only reads from `results` (the dict of per-method result dicts built by
    run_validation_method()), `mode` ("Design" or "Evaluate"), `test_start`, and
    `control_regions_val` — it does not depend on any other local state from the
    caller. METHOD_STRUCTURAL / METHOD_USER_SELECTED are module-level constants.
    """
    # ---- Method Comparison table ----
    st.subheader("Method Comparison")

    # combine_reliability_ratings() already returns the full user-facing label
    # (e.g. "🟢 High confidence"), so this is a passthrough map with a safe fallback
    # for any unexpected/legacy value.
    RELIABILITY_LABELS = {
        "🟢 High confidence": "🟢 High confidence",
        "🟡 Moderate confidence": "🟡 Moderate confidence",
        "🔴 Low confidence": "🔴 Low confidence",
        "⚪ Insufficient data": "⚪ Insufficient data",
    }

    comparison_rows = [
        {"Metric": "A. CONTROL SELECTION", "is_section": True},
        {"Metric": "Control Pool Size", "key": "control_pool_size"},
        {"Metric": "Controls Selected", "key": "controls_selected"},
        {"Metric": "Predictors Selected", "key": "n_selected_features"},
        {"Metric": "B. PRE-PERIOD FIT", "is_section": True},
        {"Metric": "Pre-Period Correlation", "key": "pre_corr"},
        {"Metric": "Pre-Period R²", "key": "pre_r2"},
        {"Metric": "Pre-Period sMAPE (%)", "key": "pre_smape"},
        {"Metric": "C1. ROLLING-ORIGIN VALIDATION - ERROR", "is_section": True},
        {"Metric": "Validation sMAPE (%)", "key": "holdout_smape"},
        {"Metric": "Validation Error Risk", "key": "rolling_validation_error_risk"},
        {"Metric": "C2. ROLLING-ORIGIN VALIDATION - BIAS", "is_section": True},
        {"Metric": "Average Bias (%)", "key": "rolling_bias_pct_mean"},
        {"Metric": "Bias Risk", "key": "rolling_bias_risk"},
        {"Metric": "D. OVERFITTING CHECK", "is_section": True},
        {"Metric": "Pre-Period vs Validation sMAPE Difference (pp)", "key": "overfit_gap_smape"},
        {"Metric": "Overfitting Risk", "key": "overfitting_risk"},
        {"Metric": "E. RESIDUAL DIAGNOSTICS", "is_section": True},
        {"Metric": "Durbin-Watson", "key": "dw_stat"},
        {"Metric": "Autocorrelation Risk", "key": "autocorrelation_risk"},
        {"Metric": "F. PLACEBO TESTING", "is_section": True},
        {"Metric": "Placebo Windows", "key": "placebo_windows"},
        {"Metric": "Average Placebo sMAPE (%)", "key": "median_placebo_smape"},
        {"Metric": "Median Placebo Uplift", "key": "median_placebo_uplift_pct"},
        {"Metric": "95% Placebo Uplift Range", "key": "placebo_range_pct"},
        {"Metric": "G. COUNTERFACTUAL CONFIDENCE", "is_section": True},
        {"Metric": "Overall Counterfactual Confidence", "key": "counterfactual_reliability"},
        {"Metric": "Key Issues", "key": "reliability_drivers"},
    ]
    show_test_impact = mode == "Evaluate" and test_start is not None
    if show_test_impact:
        comparison_rows += [
            {"Metric": "H. OBSERVED UPLIFT VS PLACEBOS", "is_section": True},
            {"Metric": "Uplift Percentile vs Placebos", "key": "placebo_percentile_rank"},
            {"Metric": "Uplift p-value", "key": "placebo_p_two_sided"},
            {"Metric": "Uplift z-score", "key": "placebo_z_score"},
            {"Metric": "I. TEST IMPACT", "is_section": True},
            {"Metric": "Observed Uplift", "key": "observed_uplift"},
            {"Metric": "Observed Uplift (%)", "key": "observed_uplift_pct"},
            {"Metric": "Test Group Actual Total", "key": "test_period_actual"},
            {
                "Metric": "Expected Total Without Test (Counterfactual)",
                "key": "test_period_counterfactual",
            },
        ]

    def _fmt_pct(v, decimals=1):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "N/A"
        return f"{v:.{decimals}f}%"

    def _fmt_num(v, decimals=1):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "N/A"
        return f"{v:.{decimals}f}"

    def get_value(key, res, method_name):
        if key == "control_pool_size":
            if method_name in [METHOD_STRUCTURAL, METHOD_USER_SELECTED]:
                return str(len(control_regions_val))
            else:
                return str(res["n_candidates"])
        elif key == "controls_selected":
            if method_name in [METHOD_STRUCTURAL, METHOD_USER_SELECTED]:
                return str(len(control_regions_val))
            else:
                return str(res["n_selected"])
        elif key == "n_selected_features":
            v = res.get("n_selected_features", None)
            return str(v) if v is not None else "N/A"
        elif key == "validation_method_label":
            return res.get("validation_method_label", "⚪ Insufficient validation history")
        elif key == "pre_corr":
            return _fmt_num(res.get("corr", np.nan), decimals=3)
        elif key == "pre_r2":
            return _fmt_num(res.get("r2", np.nan), decimals=3)
        elif key == "pre_smape":
            return _fmt_pct(res.get("smape", np.nan))
        elif key == "pre_rmse":
            return _fmt_num(res.get("rmse", np.nan))
        elif key == "dw_stat":
            dw = res.get("dw_stat", np.nan)
            if dw is None or (isinstance(dw, float) and np.isnan(dw)):
                return "N/A"
            return f"{dw:.2f}"
        elif key == "autocorrelation_risk":
            return res.get("autocorrelation_risk", "⚪ Insufficient data")
        elif key == "holdout_smape":
            return _fmt_pct(res.get("holdout_smape_mean", np.nan))
        elif key == "rolling_validation_error_risk":
            return res.get("rolling_validation_error_risk", "⚪ Insufficient data")
        elif key == "holdout_rmse":
            return _fmt_num(res.get("holdout_rmse_mean", np.nan))
        elif key == "rolling_smape_p90":
            return _fmt_pct(res.get("rolling_smape_p90", np.nan))
        elif key == "rolling_bias_pct_mean":
            return _fmt_pct(res.get("rolling_bias_pct_mean", np.nan))
        elif key == "rolling_bias_risk":
            return res.get("rolling_bias_risk", "⚪ Insufficient data")
        elif key == "overfit_gap_smape":
            v = res.get("overfit_gap_smape", np.nan)
            return (
                f"{v:.1f} pp"
                if not (v is None or (isinstance(v, float) and np.isnan(v)))
                else "N/A"
            )
        elif key == "overfit_gap_rmse":
            return _fmt_num(res.get("overfit_gap_rmse", np.nan))
        elif key == "overfitting_risk":
            return res.get("overfitting_risk", "⚪ Insufficient data")
        elif key == "reliability_drivers":
            return res.get(
                "reliability_drivers", "Insufficient validation data to assess confidence"
            )
        elif key == "counterfactual_reliability":
            reliability = res.get("counterfactual_reliability", None)
            return RELIABILITY_LABELS.get(reliability, "⚪ Insufficient data")
        elif key == "placebo_windows":
            return str(len(res["placebos"]))
        elif key == "median_placebo_uplift_pct":
            return _fmt_pct(res.get("median_placebo_uplift_pct", np.nan))
        elif key == "placebo_range_pct":
            return format_range(
                res.get("placebo_range_lower_pct", np.nan),
                res.get("placebo_range_upper_pct", np.nan),
                suffix="%",
                decimals=1,
            )
        elif key == "median_placebo_smape":
            return _fmt_pct(res.get("median_placebo_smape", np.nan))
        elif key == "p95_placebo_smape":
            return _fmt_pct(res.get("p95_placebo_smape", np.nan))
        elif key == "placebo_percentile_rank":
            return _fmt_pct(res.get("placebo_percentile_rank", np.nan))
        elif key == "placebo_p_two_sided":
            return _fmt_num(res.get("placebo_p_value_two_sided", np.nan), decimals=3)
        elif key == "placebo_z_score":
            return _fmt_num(res.get("placebo_z_score", np.nan), decimals=2)
        elif key == "observed_uplift":
            return _fmt_num(res.get("uplift", np.nan))
        elif key == "observed_uplift_pct":
            return _fmt_pct(res.get("uplift_pct", np.nan))
        elif key == "test_period_actual":
            y_test_actual = res.get("y_test_actual", None)
            if y_test_actual is None or len(y_test_actual) == 0:
                return "N/A"
            return _fmt_num(float(np.sum(y_test_actual)))
        elif key == "test_period_counterfactual":
            y_pred_test = res.get("y_pred_test", None)
            if y_pred_test is None or len(y_pred_test) == 0:
                return "N/A"
            return _fmt_num(float(np.sum(y_pred_test)))
        else:
            return "N/A"

    table_data = []
    method_names = list(results.keys())
    for row in comparison_rows:
        if row.get("is_section", False):
            new_row = {"Metric": row["Metric"]}
            for m in method_names:
                new_row[m] = ""
            table_data.append(new_row)
        else:
            new_row = {"Metric": row["Metric"]}
            for m in method_names:
                new_row[m] = get_value(row["key"], results[m], m)
            table_data.append(new_row)

    comp_df_val = pd.DataFrame(table_data)

    def style_section_rows(row):
        if row["Metric"] in [r["Metric"] for r in comparison_rows if r.get("is_section", False)]:
            return ["font-weight: bold; background-color: #f0f2f6"] * len(row)
        return [""] * len(row)

    styled_comp = comp_df_val.style.apply(style_section_rows, axis=1)
    st.dataframe(styled_comp, width="stretch", hide_index=False)

    st.caption(
        "**Rolling-Origin Validation Error** shows whether the model can predict held-out historical periods. "
        "Lower is better."
    )
    st.caption(
        "**Rolling-Origin Validation Bias** checks whether the model systematically over- or under-predicts in held-out "
        "historical periods."
    )
    st.caption(
        "**Pre-Period vs Validation sMAPE Difference** compares the model's in-sample pre-period error with its held-out rolling "
        "validation error. A large positive gap means the model looks good on the data it was fitted on, "
        "but performs worse when predicting unseen historical periods."
    )
    st.caption(
        "**Durbin-Watson** checks whether residuals are autocorrelated. Values near 2 are good. Values far "
        "below or above 2 suggest the model is missing time patterns."
    )
    st.caption(
        "**95% Placebo Uplift Range** is based on historical fake-test windows. They show how much apparent "
        "uplift could occur when no real intervention happened. If the observed test uplift sits inside "
        "this range, it may not be distinguishable from normal historical noise."
    )
    st.caption(
        "**Uplift Percentile vs Placebos** and **Uplift p-value** are empirical, derived directly from the "
        "**Placebo Windows** count shown above — their resolution is limited to roughly 1 / (that count). "
        "With few placebo windows, a p-value can only take a few discrete values (e.g. 10 windows means "
        "p can only land on multiples of 0.1), so treat a borderline result with a low placebo-window count "
        "with extra caution."
    )
    st.caption(
        "**Overall Counterfactual Confidence** is a priority-ordered summary, not a simple worst-of-four "
        "vote. Rolling Validation Error is the primary check and acts as a gate: a high-risk validation "
        "error alone makes confidence low. Overfitting, Autocorrelation Risk, and Rolling Bias are "
        "evaluated next in that order — a flag on any of them holds confidence at moderate, but only "
        "Rolling Validation Error can push it all the way down to low."
    )
    st.caption(
        "**Key Issues** lists all the high- and moderate-risk checks that drove the confidence rating, "
        "not just the single worst one. "
        "Traffic-light bands are interpretation aids based on validation diagnostics — they are not "
        "standalone hypothesis tests."
    )

    # ---- Interpretation help ----
    with st.expander("How to interpret these results", expanded=False):
        if mode == "Design":
            st.markdown("""
**Validate Test Design — How to read this**

The goal here is to assess whether your control group can reliably predict what would have happened to your test regions without any intervention. If it can, you can have more confidence in a future uplift estimate.

We recommend interpreting the checks in this order: rolling-origin validation error, then overfitting, then residual diagnostics, then rolling bias, then Overall Counterfactual Confidence as the final summary.

---

**Step 1 — Start with Rolling-Origin Validation Error**

This is the main check for whether the model can predict unseen historical data, and should be treated as the primary model-quality check. It is far more trustworthy than pre-period fit alone.

- **Rolling-Origin sMAPE (%)** — Typical percentage error when predicting the test KPI from controls. Lower validation sMAPE means the counterfactual is likely to be more trustworthy. 🟢 Low: 10% or below. 🟡 Moderate: above 10% up to 15%. 🔴 High: above 15%.
- **Rolling-Origin sMAPE — Worst Case (P90)** — The error in the weakest 10% of forecast windows. Even if the average looks fine, a high P90 means the model breaks down in certain periods.

---

**Step 2 — Then check Overfitting**

Compare pre-period fit against rolling-origin validation. A large gap means the model may look good in-sample but perform poorly on unseen data.

- **Overfitting Gap, sMAPE percentage points** — Rolling-origin validation sMAPE minus pre-period sMAPE. 🟢 Low: up to 3 percentage points. 🟡 Moderate: above 3 up to 5 percentage points. 🔴 High: above 5 percentage points. This is a validation diagnostic, not a formal statistical test.

---

**Step 3 — Then check Residual Diagnostics**

Use Durbin-Watson / autocorrelation risk to assess whether residuals are independent enough. Strong autocorrelation means the model may be missing time structure.

- **Durbin-Watson** / **Autocorrelation Risk** — Durbin-Watson is an established statistic for first-order residual autocorrelation. Values near 2 suggest little autocorrelation. 🟢 Low autocorrelation risk: 1.5 to 2.5. 🟡 Moderate autocorrelation risk: 1.2 to just under 1.5, or above 2.5 up to 2.8. 🔴 High autocorrelation risk: below 1.2 or above 2.8. These are practical diagnostic bands, not formal critical-value tests.

---

**Step 4 — Then check Rolling Bias**

Bias tells you whether the model systematically over- or under-predicts in validation windows. Rolling bias feeds into Overall Counterfactual Confidence — if bias is moderate or high, be more cautious about interpreting the uplift.

- **Rolling-Origin Bias (%)** — Whether the model consistently overshoots or undershoots. 🟢 Low: absolute bias 5% or below. 🟡 Moderate: above 5% up to 10%. 🔴 High: above 10%.

---

**Step 5 — Use Overall Counterfactual Confidence as the final summary**

- **Overall Counterfactual Confidence** — Not a simple worst-of-four vote. Rolling Validation Error is the primary check and acts as a gate: a high-risk validation error alone is enough to make confidence low. Overfitting Risk, Autocorrelation Risk, and Rolling Bias Risk are evaluated next in that priority order — a flag on any of them holds confidence at moderate, but only Rolling Validation Error can push it all the way down to low. **Key Issues** lists every high- and moderate-risk check that contributed, not just the single worst one.
    - 🟢 **High confidence** — Suitable to proceed, assuming the business context also makes sense.
    - 🟡 **Moderate confidence** — Usable, but interpret uplift cautiously and check the Key Issues.
    - 🔴 **Low confidence** — Don't rely on the counterfactual without improving the model, controls, or time window.
    - ⚪ **Insufficient data** — Not enough validation evidence to make a reliable judgement. This is a data-availability gap, not evidence that confidence is high.

Traffic-light bands are interpretation aids based on validation diagnostics. They are not standalone hypothesis tests.

---

**Step 6 — Review Placebo Testing**

Placebo tests simulate running a fake intervention across all available historical windows. A well-behaved model produces placebo uplifts clustered near zero.

- **Median Placebo Uplift** — Should be close to 0%. Large values mean the model consistently finds phantom effects.
- **95% Placebo Uplift Range** — The full spread of placebo (fake-test) uplifts. **This is your rough minimum detectable effect:** if your target uplift is smaller than this range, the design may lack power to distinguish a real signal from historical noise. A wide range also means the model is volatile — your real test uplift will need to sit clearly outside it to be credible.

---

**Step 7 — Use Pre-Period Fit as a sanity check only**

Pre-period Correlation is shown for reference but can be misleadingly high — a model can fit the pre-period well and still fail out-of-sample. Always weight the rolling-origin metrics more heavily.

---

**Rule of thumb:** Low rolling-origin sMAPE + High/Moderate Overall Counterfactual Confidence + a narrow, tight placebo distribution = a reliable test design ready to run.
            """)
        else:
            st.markdown("""
**Measure Test Impact — How to read this**

Before trusting the uplift estimate, verify the model can reliably predict the test KPI. An unreliable model produces an unreliable uplift number.

We recommend interpreting the checks in this order: rolling-origin validation error, then overfitting, then residual diagnostics, then rolling bias, then Overall Counterfactual Confidence as the final summary.

---

**Step 1 — Start with Rolling-Origin Validation Error**

This is the main check for whether the model can predict unseen historical data, and should be treated as the primary model-quality check.

- **Rolling-Origin sMAPE (%)** — Typical out-of-sample prediction error. Lower validation sMAPE means the counterfactual is likely to be more trustworthy. 🟢 Low: 10% or below. 🟡 Moderate: above 10% up to 15%. 🔴 High: above 15% — treat the uplift estimate with caution, since the counterfactual baseline is uncertain.

---

**Step 2 — Then check Overfitting**

Compare pre-period fit against rolling-origin validation. A large gap means the model may look good in-sample but perform poorly on unseen data.

- **Overfitting Gap, sMAPE percentage points** — Rolling-origin validation sMAPE minus pre-period sMAPE. 🟢 Low: up to 3 percentage points. 🟡 Moderate: above 3 up to 5 percentage points. 🔴 High: above 5 percentage points.

---

**Step 3 — Then check Residual Diagnostics**

Use Durbin-Watson / autocorrelation risk to assess whether residuals are independent enough. Strong autocorrelation means the model may be missing time structure.

- **Durbin-Watson** / **Autocorrelation Risk** — 🟢 Low autocorrelation risk: 1.5 to 2.5. 🟡 Moderate autocorrelation risk: 1.2 to just under 1.5, or above 2.5 up to 2.8. 🔴 High autocorrelation risk: below 1.2 or above 2.8. These are practical diagnostic bands, not formal critical-value tests.

---

**Step 4 — Then check Rolling Bias**

Bias tells you whether the model systematically over- or under-predicts in validation windows. A model that consistently undershoots will overstate uplift, and vice versa. If bias is moderate or high, be more cautious about interpreting the uplift.

- **Rolling-Origin Bias (%)** — 🟢 Low: absolute bias 5% or below. 🟡 Moderate: above 5% up to 10%. 🔴 High: above 10%.

---

**Step 5 — Use Overall Counterfactual Confidence as the final summary**

- **Overall Counterfactual Confidence** — Not a simple worst-of-four vote. Rolling Validation Error is the primary check and acts as a gate: a high-risk validation error alone is enough to make confidence low, particularly for data-optimised methods. Overfitting Risk, Autocorrelation Risk, and Rolling Bias Risk are evaluated next in that priority order — a flag on any of them holds confidence at moderate, but only Rolling Validation Error can push it all the way down to low. **Key Issues** lists every high- and moderate-risk check that contributed, not just the single worst one.
    - 🟢 **High confidence** — Suitable to proceed, assuming the business context also makes sense.
    - 🟡 **Moderate confidence** — Usable, but interpret uplift cautiously and check the Key Issues, particularly for data-optimised methods.
    - 🔴 **Low confidence** — Don't rely on the counterfactual without improving the model, controls, or time window.
    - ⚪ **Insufficient data** — Not enough rolling-origin history to assess this at all; treat the uplift with the same caution you would give a low-confidence result.
- **95% Placebo Uplift Range** — The range of apparent uplifts the model detects in historical periods with no intervention. Your observed uplift needs to sit clearly outside this range.

Traffic-light bands are interpretation aids based on validation diagnostics. They are not standalone hypothesis tests.

---

**Step 6 — Assess the uplift result**

- **Observed Uplift Percentile vs Placebos** — Where your observed uplift ranks relative to the distribution of historical placebo (fake-test) uplifts. 95th percentile or above is stronger evidence that the observed uplift is unusual relative to pre-period noise.
- **Observed Uplift p-value** — The placebo p-value is an empirical extremeness check: it shows how unusual the observed uplift is relative to historical fake-test windows. It is not proof of causality and should be interpreted alongside model fit, rolling-origin validation, and business context. Below 0.05 is the conventional (approximate) threshold analysts use as a rule of thumb.
- **A precision note:** both of these are only as fine-grained as the number of **Placebo Windows** available (shown in section F). With, say, 10 placebo windows, the p-value can only land on multiples of 0.1 — it's not possible to observe a "real" 0.02. Check the Placebo Windows count before leaning heavily on a borderline p-value or percentile.

---

**Step 7 — Compare methods**

If you ran multiple methods (Structural, Data-Optimised), look for agreement. When both methods produce similar uplift estimates, both show good out-of-sample fit, and both show High/Moderate Overall Counterfactual Confidence, confidence in the result is higher.

---

**Rule of thumb:** Low rolling-origin sMAPE + High/Moderate Overall Counterfactual Confidence + observed uplift outside the placebo range + a small p-value = a result with stronger evidence behind it, though still not proof of causality on its own.
            """)


def render_time_series_validation(mode: str):
    """
    Shared UI for Design (Tab 2) and Evaluate (Tab 3).
    mode is either "Design" or "Evaluate".
    Pass the literal string used in the existing working-file logic.
    """
    if st.session_state.final_controls is None:
        st.info("Complete the Matching Setup in the **Region Matching** tab first.")
        return

    # -------------------------------------------------------------------------
    # Session state for validation (persist across reruns)
    # -------------------------------------------------------------------------
    if "validation_results" not in st.session_state:
        st.session_state.validation_results = None
    if "validation_triggered" not in st.session_state:
        st.session_state.validation_triggered = False
    if "kpi_long_df" not in st.session_state:
        st.session_state.kpi_long_df = None
    if "kpi_regional_dataset" not in st.session_state:
        st.session_state.kpi_regional_dataset = None
    if "kpi_regional_source_fingerprint" not in st.session_state:
        st.session_state.kpi_regional_source_fingerprint = None
    if "kpi_quality_report" not in st.session_state:
        st.session_state.kpi_quality_report = None
    if "kpi_rejected_rows" not in st.session_state:
        st.session_state.kpi_rejected_rows = None
    if "kpi_mapping_report" not in st.session_state:
        st.session_state.kpi_mapping_report = None
    if "kpi_mapping_fingerprint" not in st.session_state:
        st.session_state.kpi_mapping_fingerprint = None
    if "kpi_available_dates" not in st.session_state:
        st.session_state.kpi_available_dates = []
    if "kpi_metric_options" not in st.session_state:
        st.session_state.kpi_metric_options = []
    if "kpi_source_bytes" not in st.session_state:
        st.session_state.kpi_source_bytes = None
    if "kpi_candidate_universe" not in st.session_state:
        st.session_state.kpi_candidate_universe = []
    if "kpi_pattern_source_bytes" not in st.session_state:
        st.session_state.kpi_pattern_source_bytes = None
    if "kpi_pattern_regional_dataset" not in st.session_state:
        st.session_state.kpi_pattern_regional_dataset = None
    if "kpi_pattern_date_range" not in st.session_state:
        st.session_state.kpi_pattern_date_range = None
    if "file_upload_key" not in st.session_state:
        st.session_state.file_upload_key = 0
    if "bayesian_results" not in st.session_state:
        st.session_state.bayesian_results = None
    if "bayesian_interpretation_visible" not in st.session_state:
        st.session_state.bayesian_interpretation_visible = False

    mode_prefix = "design" if mode == "Design" else "evaluate"
    _active_frozen = active_frozen_version(_experiment_record()) if mode == "Evaluate" else None
    _inherited_frozen = st.session_state.get("evaluate_inherited_frozen_design")
    if mode == "Evaluate" and _active_frozen:
        st.markdown("### Approved design inheritance")
        st.caption(
            f"Active frozen design: version {_active_frozen['version']} at "
            f"{_active_frozen['frozen_at']}. Load its executed regions and planned "
            "periods as the starting point for this completed-test evaluation."
        )
        if _inherited_frozen and _inherited_frozen.get("version") == _active_frozen["version"]:
            st.success(
                f"Using active frozen design version {_inherited_frozen['version']} as evaluation defaults. "
                "Live changes remain visible and will be recorded by the evaluation run."
            )
        if st.button(
            f"📌 Use active frozen design (v{_active_frozen['version']})",
            key="evaluate_inherit_frozen_design",
        ):
            _frozen_design = dict(_active_frozen.get("design") or {})
            _frozen_matching = dict(_frozen_design.get("matching") or {})
            _frozen_regions = _frozen_design.get("test_regions") or _frozen_matching.get(
                "test_regions", []
            )
            _frozen_controls = _frozen_design.get("control_regions") or _frozen_matching.get(
                "selected_controls", []
            )
            st.session_state.evaluate_inherited_frozen_design = {
                "version": _active_frozen["version"],
                "planned": dict(_active_frozen.get("planned") or {}),
                "design": _frozen_design,
            }
            if _frozen_regions:
                st.session_state.selected_experiment_regions = list(_frozen_regions)
            _geo_key = globals().get("geo_col")
            _controls_df = st.session_state.get("final_controls")
            if _controls_df is not None and _geo_key in _controls_df.columns and _frozen_controls:
                _frozen_control_set = {str(r) for r in _frozen_controls}
                _available_control_set = set(_controls_df[_geo_key].dropna().astype(str))
                if _frozen_control_set <= _available_control_set:
                    st.session_state.final_controls = _controls_df[
                        _controls_df[_geo_key].astype(str).isin(_frozen_control_set)
                    ].copy()
                else:
                    st.warning(
                        "Some frozen control regions are not present in the current matching "
                        "result; the current controls were retained for review."
                    )
            _frozen_frequency = _active_frozen.get("planned", {}).get(
                "time_series_frequency"
            ) or _frozen_design.get("frequency")
            if _frozen_frequency in {"weekly", "daily"}:
                st.session_state.evaluate_time_series_frequency = _frozen_frequency
            st.session_state.validation_results = None
            st.session_state.validation_triggered = False
            st.session_state.experiment_validation_inputs = None
            _clear_bayesian_state()
            _clear_production_power_state()
            st.rerun()

    # -------------------------------------------------------------------------
    # Helper to clear previous validation results
    # -------------------------------------------------------------------------
    def clear_validation_state():
        st.session_state.validation_results = None
        st.session_state.validation_triggered = False
        _clear_bayesian_state()
        _clear_production_power_state()
        # Experiment record: the validation/Bayesian inputs are gone, so those
        # stages reconcile to stale on the next rerun (Stage 4).
        st.session_state.experiment_validation_inputs = None
        st.session_state.experiment_bayesian_inputs = None

    def clear_uploaded_kpi_state():
        """Clear validation/Bayesian results AND the previously parsed KPI file, so a newly
        uploaded file can't leave stale parsed data (dates, metric list, long-format df) behind."""
        clear_validation_state()
        st.session_state.kpi_long_df = None
        st.session_state.kpi_regional_dataset = None
        st.session_state.kpi_regional_source_fingerprint = None
        st.session_state.kpi_quality_report = None
        st.session_state.kpi_rejected_rows = None
        st.session_state.kpi_mapping_report = None
        st.session_state.kpi_mapping_fingerprint = None
        st.session_state.kpi_available_dates = []
        st.session_state.kpi_metric_options = []
        st.session_state.kpi_source_bytes = None
        st.session_state.kpi_candidate_universe = []
        st.session_state.experiment_geo_workbook_cache = None
        st.session_state.experiment_market_sheet_cache = None

    # -------------------------------------------------------------------------
    # 1. Data Source
    # -------------------------------------------------------------------------
    st.markdown("### Data Source")
    st.caption("Upload your historical KPI data and select the metric to model.")

    # KPI Pattern has already prepared the sidebar workbook through the shared
    # canonical contract. Reuse that dataset in validation instead of asking
    # the analyst to upload the same workbook a second time.
    shared_kpi_dataset = (
        st.session_state.get("kpi_pattern_regional_dataset")
        if st.session_state.get("kpi_pattern_mode")
        else None
    )
    if shared_kpi_dataset is not None:
        if (
            st.session_state.get("kpi_regional_source_fingerprint")
            != shared_kpi_dataset.source_data_fingerprint
        ):
            clear_uploaded_kpi_state()
        st.session_state.kpi_regional_source_fingerprint = (
            shared_kpi_dataset.source_data_fingerprint
        )
        uploaded_file = None
        st.info(
            "Using the KPI Pattern workbook and aggregation/metric selections "
            "already prepared in Region Matching."
        )
    else:
        uploaded_file = st.file_uploader(
            "Upload historical KPI Excel file",
            type=["xlsx"],
            key=f"kpi_uploader_{mode_prefix}_{st.session_state.file_upload_key}",
            help="Simple format: column 1 = region name, column 2 = metric name, then date columns. "
            "Aggregated format: column 1 = raw key (ignored), several aggregation-level columns, "
            "a metric column, then date columns — pick which columns to use after uploading.",
            on_change=clear_uploaded_kpi_state,
        )

    if uploaded_file is None and shared_kpi_dataset is None:
        st.info("📂 Please upload a historical KPI Excel file to begin.")
        return

    # ---- Peek at columns to detect file layout: simple 2-column (region, metric) vs
    # the newer aggregated multi-level format (raw key + multiple aggregation-level
    # columns + metric column) — see load_and_reshape_kpi() for full format details.
    # Selectors (when needed) always render live, with on_change wired to
    # clear_uploaded_kpi_state, so changing the selection re-parses the file rather
    # than only taking effect on first upload. ----
    _kpi_agg_col = None
    _kpi_metric_col = None
    if shared_kpi_dataset is not None:
        _kpi_agg_col = shared_kpi_dataset.config.aggregation_column
        _kpi_metric_col = shared_kpi_dataset.config.metric_column
    else:
        try:
            _kpi_peek_df = pd.read_excel(uploaded_file, engine="calamine", header=0, nrows=5)
        except Exception:
            uploaded_file.seek(0)
            _kpi_peek_df = pd.read_excel(uploaded_file, engine="openpyxl", header=0, nrows=5)
        uploaded_file.seek(0)
        _kpi_peek_date_cols = detect_date_columns(_kpi_peek_df)
        _kpi_peek_non_date_cols = [c for c in _kpi_peek_df.columns if c not in _kpi_peek_date_cols]

    if shared_kpi_dataset is None and len(_kpi_peek_non_date_cols) > 2:
        # ---- In KPI Pattern mode, the aggregation-level and metric columns were already
        # chosen in Step 1 (Region Matching sidebar) — carry them over instead of asking
        # again, as long as this file actually has those same column names. ----
        _carried_agg_col = st.session_state.get("kpi_pattern_agg_col_sidebar")
        _carried_metric_col = st.session_state.get("kpi_pattern_metric_col")
        _can_carry_over = (
            st.session_state.get("kpi_pattern_mode")
            and _carried_agg_col in _kpi_peek_non_date_cols
            and _carried_metric_col in _kpi_peek_non_date_cols
            and _carried_agg_col != _carried_metric_col
        )
        if _can_carry_over:
            _kpi_agg_col = _carried_agg_col
            _kpi_metric_col = _carried_metric_col
            st.caption(
                f"ℹ️ Using **{_kpi_agg_col}** as the aggregation level and **{_kpi_metric_col}** "
                f"as the metric column, carried over from Region Matching."
            )
        else:
            if st.session_state.get("kpi_pattern_mode"):
                st.warning(
                    "This file's columns don't match the aggregation level/metric column chosen "
                    "in Region Matching — please select them for this file."
                )
            st.markdown("**This file has multiple aggregation-level columns — pick which to use:**")
            _kpi_agg_candidates = list(_kpi_peek_non_date_cols[1:])
            _kpi_default_metric = detect_metric_column(_kpi_peek_non_date_cols)
            col_a, col_b = st.columns(2)
            with col_a:
                _kpi_metric_col = st.selectbox(
                    "Metric column",
                    _kpi_agg_candidates,
                    index=(
                        _kpi_agg_candidates.index(_kpi_default_metric)
                        if _kpi_default_metric in _kpi_agg_candidates
                        else len(_kpi_agg_candidates) - 1
                    ),
                    key=f"kpi_upload_metric_col_{mode_prefix}",
                    on_change=clear_uploaded_kpi_state,
                )
            with col_b:
                _kpi_agg_options = [c for c in _kpi_agg_candidates if c != _kpi_metric_col]
                _kpi_agg_col = st.selectbox(
                    "Aggregation level",
                    _kpi_agg_options,
                    key=f"kpi_upload_agg_col_{mode_prefix}",
                    help="Which column to group and sum by. For consistency, use the same aggregation "
                    "level you matched on in the Region Matching tab.",
                    on_change=clear_uploaded_kpi_state,
                )

    if st.session_state.kpi_long_df is None and shared_kpi_dataset is not None:
        st.session_state.kpi_source_bytes = st.session_state.get("kpi_pattern_source_bytes")
        st.session_state.kpi_long_df = shared_kpi_dataset.legacy_data.copy()
        st.session_state.kpi_regional_dataset = shared_kpi_dataset
        st.session_state.kpi_regional_source_fingerprint = (
            shared_kpi_dataset.source_data_fingerprint
        )
        st.session_state.kpi_quality_report = shared_kpi_dataset.quality
        st.session_state.kpi_rejected_rows = shared_kpi_dataset.rejected_rows
        st.session_state.kpi_available_dates = sorted(
            st.session_state.kpi_long_df["date"].dt.date.unique()
        )
        st.session_state.kpi_metric_options = sorted(
            st.session_state.kpi_long_df["metric_name"].unique()
        )
    elif st.session_state.kpi_long_df is None:
        with st.spinner("Reading KPI file..."):
            parsed = load_and_reshape_kpi(
                uploaded_file, agg_col=_kpi_agg_col, metric_col=_kpi_metric_col
            )
            df_long = parsed.data
            st.session_state.kpi_source_bytes = uploaded_file.getvalue()
            st.session_state.kpi_long_df = df_long
            st.session_state.kpi_regional_dataset = parsed.regional_dataset
            st.session_state.kpi_regional_source_fingerprint = (
                parsed.regional_dataset.source_data_fingerprint
                if parsed.regional_dataset is not None
                else None
            )
            st.session_state.kpi_quality_report = parsed.quality
            st.session_state.kpi_rejected_rows = parsed.rejected_rows
            st.session_state.kpi_available_dates = sorted(df_long["date"].dt.date.unique())
            st.session_state.kpi_metric_options = sorted(df_long["metric_name"].unique())

    if st.session_state.kpi_long_df is None:
        st.error("Failed to read the KPI file.")
        st.stop()

    df_long = st.session_state.kpi_long_df
    available_dates = st.session_state.kpi_available_dates
    metric_options = st.session_state.kpi_metric_options

    if not metric_options:
        st.error("No metric names found in second column of the KPI file.")
        st.stop()

    with st.expander("Summary of Uploaded Data", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Regions detected", df_long["region_raw"].nunique())
        col2.metric("KPIs found", len(metric_options))
        col3.metric(
            "Date range",
            f"{available_dates[0].strftime('%d %b %y')} – {available_dates[-1].strftime('%d %b %y')}",
        )
        col4.metric(
            "Observed date points",
            len(available_dates),
            help="Number of distinct dates found in the uploaded file, independent of the selected time series frequency.",
        )

    st.markdown(
        """
<div style="background:#E6F7F5; border-left:4px solid #0F766E; border-radius:6px; padding:0.75rem 1rem 0.25rem 1rem; margin-bottom:0.75rem;">
<span style="font-weight:600; color:#0F766E; font-size:1rem;">📊 Select KPI</span><br>
<span style="color:#4B5563; font-size:0.875rem;">Choose the metric you want to model. This drives all validation, placebo, and uplift results.</span>
</div>
""",
        unsafe_allow_html=True,
    )
    selected_metric = st.selectbox(
        "KPI to analyse",
        metric_options,
        key=f"{mode_prefix}_selected_metric",
        help="The metric used to assess how well the control regions track the test regions over time. Choose the KPI you plan to measure in your geo test.",
        on_change=clear_validation_state,
        label_visibility="collapsed",
    )
    kpi_file_name = getattr(uploaded_file, "name", None) or (
        "KPI Pattern sidebar workbook" if shared_kpi_dataset is not None else None
    )
    kpi_file_size = getattr(uploaded_file, "size", None) or (
        len(st.session_state.get("kpi_source_bytes") or b"")
        if shared_kpi_dataset is not None
        else None
    )

    # -------------------------------------------------------------------------
    # Pre-run region-mapping report — computed as soon as the uploaded file,
    # market, geography level, mapping source and selected metric are known,
    # BEFORE the Run action, so mapped/unmapped geographies are reported and
    # modelling is blocked when a required selected test region has no mapped
    # data. Versioned by a deterministic input fingerprint: the report is
    # reused across reruns unless a mapping-relevant input changes (file,
    # market, geography level, selected metric, aggregation column, mapping
    # source), so display-only interactions never recompute it.
    # -------------------------------------------------------------------------
    def _recompute_mapping_report():
        """Build the current region-mapping report (pure mapping + adapter)."""
        if st.session_state.get("kpi_pattern_mode"):
            _adobe_to_geo = {}
        else:
            try:
                _master_df = load_market_sheet(DATA_PATH, market, _workbook_identity_tuple())
                _adobe_to_geo = dict(
                    zip(
                        _master_df[ADOBE_COL].astype(str).str.strip(),
                        _master_df[geo_col].astype(str).str.strip(),
                    )
                )
            except Exception as e:
                st.warning(f"⚠️ Could not load the region mapping table: {e}")
                return None
        _valid_regions = _current_candidate_universe(agg_df, geo_col)
        st.session_state.kpi_candidate_universe = sorted(str(r) for r in _valid_regions)
        return compute_region_mapping_report(
            df_long, _valid_regions, _adobe_to_geo, metric_name=selected_metric
        )

    _mapping_fingerprint = region_mapping_fingerprint(
        file_name=kpi_file_name,
        file_size=kpi_file_size,
        file_sha256=(
            sha256_bytes(st.session_state["kpi_source_bytes"])
            if st.session_state.get("kpi_source_bytes")
            else None
        ),
        market=market,
        geo_col=geo_col,
        selected_metric=selected_metric,
        agg_col=_kpi_agg_col,
        mapping_source=(
            "kpi_pattern" if st.session_state.get("kpi_pattern_mode") else "structural"
        ),
        kpi_pattern_source_digest=(
            sha256_bytes(st.session_state["kpi_pattern_source_bytes"])
            if st.session_state.get("kpi_pattern_source_bytes")
            else None
        ),
        candidate_universe_digest=_current_candidate_universe_digest(agg_df, geo_col),
        kpi_pattern_date_range=st.session_state.get("kpi_pattern_date_range"),
        mapping_reference_digest=_current_mapping_reference_digest(geo_col, market=market),
    )
    if st.session_state.get("kpi_mapping_fingerprint") != _mapping_fingerprint:
        st.session_state.kpi_mapping_report = _recompute_mapping_report()
        st.session_state.kpi_mapping_fingerprint = _mapping_fingerprint

    # ---- Data-quality report (parse + region mapping), shown before any
    # validation / evaluation / KPI-pattern / Bayesian run. Blocking errors
    # (when present) prevent modelling; warnings never silently block. ----
    render_kpi_quality_report(
        st.session_state.get("kpi_quality_report"),
        rejected_rows=st.session_state.get("kpi_rejected_rows"),
        mapping_report=st.session_state.get("kpi_mapping_report"),
    )

    # -------------------------------------------------------------------------
    # 1b. Observed dates for the selected KPI — computed from the actual dates present
    # for the selected metric, so frequency inference, period counts, and slider defaults
    # all reflect real data coverage for THIS metric rather than the whole file or a
    # calendar assumption (robust to missing/irregular dates, and to metrics with
    # different date coverage than each other).
    # -------------------------------------------------------------------------
    _metric_dates_series = df_long.loc[df_long["metric_name"] == selected_metric, "date"]
    if not _metric_dates_series.empty:
        _metric_dates_all = pd.to_datetime(_metric_dates_series).dt.normalize()
    else:
        _metric_dates_all = pd.to_datetime(pd.Series(available_dates))

    def _observed_period_count(start_val, end_val):
        if start_val is None or end_val is None:
            return None
        start_ts = pd.Timestamp(start_val)
        end_ts = pd.Timestamp(end_val)
        mask = (_metric_dates_all >= start_ts) & (_metric_dates_all <= end_ts)
        return int(_metric_dates_all[mask].nunique())

    # -------------------------------------------------------------------------
    # 1c. Time series frequency (shared by Validate Test Design and Measure Test
    # Impact, and passed through to Bayesian TBR via validation_results)
    # -------------------------------------------------------------------------
    st.markdown("**Time series frequency**")
    time_series_frequency = st.radio(
        "Time series frequency",
        options=["weekly", "daily"],
        format_func=lambda v: "Weekly" if v == "weekly" else "Daily",
        index=0 if st.session_state.get("time_series_frequency", "weekly") == "weekly" else 1,
        key=f"{mode_prefix}_time_series_frequency",
        horizontal=True,
        help="Weekly data uses a 1-week lag and week-based windows. Daily data uses a 7-day lag (same day-of-week comparison) and day-based windows.",
        on_change=clear_validation_state,
        label_visibility="collapsed",
    )
    st.session_state.time_series_frequency = time_series_frequency
    freq_config = get_frequency_config(time_series_frequency)

    if time_series_frequency == "daily":
        st.info(
            "ℹ️ Daily data can be noisier than weekly data and often contains day-of-week effects. "
            "Use longer pre-periods, check rolling-origin validation carefully, and prefer the 7-day "
            "lag option if lagged controls are enabled.\n\n"
            "Daily analysis is useful when you need more granular monitoring, but weekly aggregation "
            "is usually more stable for final geo-test readouts. Daily results should be judged "
            "carefully using rolling-origin validation, placebo ranges and model validation diagnostics."
        )

    # Frequency inference uses the SELECTED METRIC's own dates (not the whole file), since
    # different metrics can have different date coverage. A confirmed daily-vs-weekly
    # mismatch is treated as a hard blocker (not just a soft suggestion) because it can
    # silently change how lags behave and make results misleading — see the checkbox below.
    _inferred_freq = infer_time_series_frequency(_metric_dates_all)
    frequency_mismatch_detected = False
    if _inferred_freq == "daily" and time_series_frequency == "weekly":
        frequency_mismatch_detected = True
        st.error(
            "The uploaded KPI dates look daily, but weekly mode is selected. "
            "Weekly mode expects already weekly-aggregated data and does not aggregate daily rows automatically. "
            "In this mode, a 1-week lag is implemented as a 1-row lag, which would behave like a 1-day lag on daily data."
        )
    elif _inferred_freq == "weekly" and time_series_frequency == "daily":
        frequency_mismatch_detected = True
        st.error(
            "The uploaded KPI dates look weekly, but daily mode is selected. "
            "Daily mode expects daily rows and uses a true calendar 7-day lag. "
            "Please switch to weekly mode unless the file genuinely contains daily data."
        )
    elif _inferred_freq != "unknown" and _inferred_freq != time_series_frequency:
        # Covers any other inferred/selected mismatch not caught by the two explicit cases above.
        frequency_mismatch_detected = True
        st.error(
            f"The uploaded data looks like it may be **{_inferred_freq}** data (based on the typical "
            f"gap between dates), but **{'Weekly' if time_series_frequency == 'weekly' else 'Daily'}** "
            f"is currently selected. This mismatch can make lag behaviour and validation results misleading."
        )

    frequency_mismatch_acknowledged = True
    if frequency_mismatch_detected:
        frequency_mismatch_acknowledged = st.checkbox(
            "I understand the frequency mismatch and want to continue",
            value=False,
            key=f"{mode_prefix}_frequency_mismatch_ack",
        )
        if not frequency_mismatch_acknowledged:
            st.info(
                "Validation and Bayesian TBR are disabled until the frequency mismatch above is acknowledged or resolved."
            )
    st.session_state.frequency_mismatch_blocked = (
        frequency_mismatch_detected and not frequency_mismatch_acknowledged
    )

    # -------------------------------------------------------------------------
    # 2. Analysis Type header (static — driven by the tab the user is in)
    # -------------------------------------------------------------------------
    if mode == "Design":
        selected_label = "Design a future geo test"
    else:
        selected_label = "Evaluate a completed geo test"

    date_options = {d.strftime("%d %b %y"): d for d in available_dates}
    date_list = list(date_options.keys())

    if mode == "Evaluate" and _inherited_frozen:
        _frozen_design = _inherited_frozen.get("design") or {}
        _frozen_source = _frozen_design.get("source_data_fingerprint")
        _current_source = getattr(
            st.session_state.get("kpi_regional_dataset"), "source_data_fingerprint", None
        )
        if _frozen_source and _current_source and _frozen_source != _current_source:
            st.warning(
                "The active frozen design was created from a different KPI source fingerprint. "
                "Its dates and regions were loaded as defaults, but this evaluation must be "
                "reviewed against the current source before it is run."
            )
        if not _inherited_frozen.get("date_defaults_applied"):
            _frozen_planned = _inherited_frozen.get("planned") or {}

            def _frozen_date_label(value):
                if value is None:
                    return None
                try:
                    return pd.Timestamp(value).strftime("%d %b %y")
                except Exception:
                    return None

            for _widget_key, _planned_key in (
                ("evaluate_pre_start", "pre_start"),
                ("evaluate_pre_end", "pre_end"),
                ("evaluate_test_start", "test_start"),
                ("evaluate_test_end", "test_end"),
                ("evaluate_post_start", "post_start"),
                ("evaluate_post_end", "post_end"),
            ):
                _label = _frozen_date_label(_frozen_planned.get(_planned_key))
                if _label in date_options:
                    st.session_state[_widget_key] = _label
            st.session_state.evaluate_use_post = bool(_frozen_planned.get("use_post", False))
            _inherited_frozen["date_defaults_applied"] = True
            st.session_state.evaluate_inherited_frozen_design = _inherited_frozen

    # -------------------------------------------------------------------------
    # 3. Configuration (depends on mode) — EXACTLY as in working file
    # -------------------------------------------------------------------------
    insufficient_pre_period = False
    if mode == "Design":
        st.markdown("---")
        st.markdown("### Historical Period")
        st.caption(
            "Define the historical date range used to assess whether test and control regions move together."
        )

        col_start, col_end = st.columns(2)
        with col_start:
            design_start_label = st.selectbox(
                "Historical period start",
                date_list,
                index=0,
                key=f"{mode_prefix}_design_start",
                on_change=clear_validation_state,
            )
            design_start = date_options[design_start_label]
        with col_end:
            design_end_label = st.selectbox(
                "Historical period end",
                date_list,
                index=len(date_list) - 1,
                key=f"{mode_prefix}_design_end",
                on_change=clear_validation_state,
            )
            design_end = date_options[design_end_label]

        if design_start >= design_end:
            st.error("Start date must be before end date.")
            st.stop()

        pre_start = pd.Timestamp(design_start)
        pre_end = pd.Timestamp(design_end)
        test_start = None
        test_end = None
        use_post = False
        post_start = None
        post_end = None
        compute_uplift = True
        summary_label = "Design period"

        st.markdown("---")
        st.markdown("### Validation & Placebo Settings")
        _period_divisor = 1 if freq_config["frequency"] == "daily" else 7
        pre_periods_design = _observed_period_count(design_start, design_end)
        if not pre_periods_design:
            # Fallback to a calendar-span estimate if observed dates couldn't be computed
            pre_periods_design = (
                pd.Timestamp(design_end) - pd.Timestamp(design_start)
            ).days // _period_divisor + 1
        default_placebo_len = freq_config["default_validation_horizon_periods"]
        _min_training_floor = 6 if freq_config["frequency"] == "weekly" else 14
        _placebo_slider_min = 2 if freq_config["frequency"] == "weekly" else 7
        _placebo_slider_max = 12 if freq_config["frequency"] == "weekly" else 90

        _slider_col1, _slider_col2 = st.columns(2)
        with _slider_col1:
            _max_min_training = max(_min_training_floor, pre_periods_design - default_placebo_len)
            _default_min_training = min(
                freq_config["default_min_training_periods"], _max_min_training
            )
            min_training_periods = st.slider(
                f"Minimum training period ({freq_config['period_label_plural']})",
                min_value=_min_training_floor,
                max_value=_max_min_training,
                value=_default_min_training,
                step=1,
                key=f"{mode_prefix}_min_training_slider",
                help=f"Minimum {freq_config['period_label_plural']} of history required before each validation or placebo window. Higher = stricter and more realistic, but fewer windows are generated.",
                on_change=clear_validation_state,
            )
        with _slider_col2:
            _placebo_default_value = min(
                max(default_placebo_len, _placebo_slider_min), _placebo_slider_max
            )
            placebo_length_periods = st.slider(
                f"Test & placebo window length ({freq_config['period_label_plural']})",
                min_value=_placebo_slider_min,
                max_value=_placebo_slider_max,
                value=_placebo_default_value,
                step=1,
                key=f"{mode_prefix}_placebo_slider",
                help="Length of each simulated test window used for placebo testing and rolling-origin validation. Set this to match your planned test duration.",
                on_change=clear_validation_state,
            )

        # ---- Definitive pre-period sufficiency check, using the ACTUAL selected slider
        # values (not just their floors) — this is what run_validation_method will use to
        # build at least one rolling-origin / placebo window. ----
        insufficient_pre_period = pre_periods_design < (
            min_training_periods + placebo_length_periods
        )
        if insufficient_pre_period:
            st.warning(
                "⚠️ Not enough pre-period observations for the selected minimum training period and "
                "validation window. Choose a longer pre-period, shorter validation window, or switch to "
                "weekly aggregation."
            )

    else:  # Evaluate
        st.markdown("---")
        st.markdown("### Define Test Periods")
        st.caption("Set the pre‑test, test, and (optionally) post‑test periods.")

        st.markdown("**Pre‑test period**")
        col_pre1, col_pre2 = st.columns(2)
        with col_pre1:
            pre_start_label = st.selectbox(
                "Start",
                date_list,
                index=0,
                key=f"{mode_prefix}_pre_start",
                on_change=clear_validation_state,
            )
            pre_start = date_options[pre_start_label]
        with col_pre2:
            pre_end_idx = min(len(date_list) - 1, int(len(date_list) * 0.75))
            pre_end_label = st.selectbox(
                "End",
                date_list,
                index=pre_end_idx,
                key=f"{mode_prefix}_pre_end",
                on_change=clear_validation_state,
            )
            pre_end = date_options[pre_end_label]

        st.markdown("**Test period**")
        col_test1, col_test2 = st.columns(2)
        with col_test1:
            test_start_idx = min(max(0, len(date_list) - 2), pre_end_idx + 5)
            test_start_label = st.selectbox(
                "Start",
                date_list,
                index=test_start_idx,
                key=f"{mode_prefix}_test_start",
                on_change=clear_validation_state,
            )
            test_start = date_options[test_start_label]
        with col_test2:
            test_end_idx = min(len(date_list) - 1, test_start_idx + 5)
            test_end_label = st.selectbox(
                "End",
                date_list,
                index=test_end_idx,
                key=f"{mode_prefix}_test_end",
                on_change=clear_validation_state,
            )
            test_end = date_options[test_end_label]

        use_post = st.checkbox(
            "Include post‑test period",
            value=False,
            key=f"{mode_prefix}_use_post",
            on_change=clear_validation_state,
        )
        if use_post:
            st.markdown("**Post‑test period**")
            col_post1, col_post2 = st.columns(2)
            with col_post1:
                post_start_idx = min(len(date_list) - 1, test_end_idx + 2)
                post_start_label = st.selectbox(
                    "Start",
                    date_list,
                    index=post_start_idx,
                    key=f"{mode_prefix}_post_start",
                    on_change=clear_validation_state,
                )
                post_start = date_options[post_start_label]
            with col_post2:
                post_end_label = st.selectbox(
                    "End",
                    date_list,
                    index=len(date_list) - 1,
                    key=f"{mode_prefix}_post_end",
                    on_change=clear_validation_state,
                )
                post_end = date_options[post_end_label]
        else:
            post_start = post_end = None

        # ---- Validation window settings ----
        st.markdown("---")
        st.markdown("### Validation & Placebo Settings")
        _period_divisor = 1 if freq_config["frequency"] == "daily" else 7
        if test_start is not None and test_end is not None:
            default_placebo_len = _observed_period_count(test_start, test_end)
            if not default_placebo_len:
                # Fallback to a calendar-span estimate if observed dates couldn't be computed
                if freq_config["frequency"] == "daily":
                    default_placebo_len = max(2, (test_end - test_start).days + 1)
                else:
                    default_placebo_len = max(2, (test_end - test_start).days // 7 + 1)
            default_placebo_len = max(2, default_placebo_len)
        else:
            default_placebo_len = freq_config["default_validation_horizon_periods"]
        pre_periods_eval = _observed_period_count(pre_start, pre_end)
        if not pre_periods_eval:
            pre_periods_eval = (
                pd.Timestamp(pre_end) - pd.Timestamp(pre_start)
            ).days // _period_divisor + 1
        _min_training_floor = 6 if freq_config["frequency"] == "weekly" else 14
        # Note: unlike Design mode, there's no _placebo_slider_min/_placebo_slider_max here —
        # placebo_length_periods is locked to default_placebo_len below, not user-adjustable.

        _slider_col1, _slider_col2 = st.columns(2)
        with _slider_col1:
            _max_min_training = max(_min_training_floor, pre_periods_eval - default_placebo_len)
            _default_min_training = min(
                freq_config["default_min_training_periods"], _max_min_training
            )
            min_training_periods = st.slider(
                f"Minimum training period ({freq_config['period_label_plural']})",
                min_value=_min_training_floor,
                max_value=_max_min_training,
                value=_default_min_training,
                step=1,
                key=f"{mode_prefix}_min_training_slider",
                help=f"Minimum {freq_config['period_label_plural']} of history required before each validation or placebo window. Higher = stricter and more realistic, but fewer windows are generated.",
                on_change=clear_validation_state,
            )
        with _slider_col2:
            # ---- LOCKED, not a slider, in Evaluate mode. ----
            # The observed uplift is always computed over the actual test_start..test_end
            # dates (see run_validation_method()), so every placebo window used to build
            # the comparison distribution — and the rolling-origin validation horizon,
            # which is deliberately kept equal to it (see cv_horizon in
            # run_validation_method()) — MUST use that same window length. If this were
            # independently adjustable, the observed uplift (summed over N_test periods)
            # could be compared against placebo uplifts summed over a different number of
            # periods, silently invalidating the percentile rank, p-value, and z-score in
            # the "Observed Uplift vs Placebos" section — cumulative uplift and its
            # variance both scale with window length, so the two would no longer be on
            # the same scale.
            placebo_length_periods = default_placebo_len
            st.metric(
                f"Test & placebo window length ({freq_config['period_label_plural']})",
                placebo_length_periods,
            )
            st.caption(
                "Locked to your observed test period length so placebo windows and "
                "rolling-origin validation folds stay directly comparable to your actual "
                "test."
            )

        # ---- Definitive pre-period sufficiency check, using the ACTUAL selected slider
        # values (not just their floors) — this is what run_validation_method will use to
        # build at least one rolling-origin / placebo window. ----
        insufficient_pre_period = pre_periods_eval < (min_training_periods + placebo_length_periods)
        if insufficient_pre_period:
            st.warning(
                "⚠️ Not enough pre-period observations for the selected minimum training period and "
                "validation window. Choose a longer pre-period, shorter validation window, or switch to "
                "weekly aggregation."
            )

        # Convert to Timestamps and validate
        pre_start = pd.Timestamp(pre_start)
        pre_end = pd.Timestamp(pre_end)
        test_start = pd.Timestamp(test_start)
        test_end = pd.Timestamp(test_end)
        if use_post and post_start is not None:
            post_start = pd.Timestamp(post_start)
            post_end = pd.Timestamp(post_end)

        if pre_start >= pre_end:
            st.error("Pre‑test period start must be before end.")
            st.stop()
        if test_start >= test_end:
            st.error("Test period start must be before end.")
            st.stop()
        if test_start <= pre_end:
            st.warning("Test period starts before pre‑test period ends. Consider adjusting.")
        compute_uplift = True
        summary_label = "Pre-test period"

    # -------------------------------------------------------------------------
    # 3c. Lagged Controls Option (applies to Validate Test Design, Measure Test
    # Impact, and — via the shared session_state flag — Bayesian TBR)
    # -------------------------------------------------------------------------
    st.markdown("---")
    include_lagged_controls = st.checkbox(
        f"Include {freq_config['lag_label']} lagged controls",
        value=st.session_state.get("include_lagged_controls", False),
        key=f"{mode_prefix}_include_lagged_controls",
        help=(
            f"Adds each control region\u2019s KPI from {freq_config['lag_periods']} "
            f"{freq_config['period_label_singular'] if freq_config['lag_periods'] == 1 else freq_config['period_label_plural']} "
            "earlier as an additional predictor. This can help when the test region follows control-region "
            "movements with a short delay, but it increases the number of predictors and should be judged "
            "using rolling-origin validation."
            + (
                " For daily data, the 7-day lag compares the same day of week to avoid confusing day-of-week "
                "seasonality with a true lagged relationship."
                if freq_config["frequency"] == "daily"
                else ""
            )
        ),
        on_change=clear_validation_state,
    )
    st.session_state.include_lagged_controls = include_lagged_controls

    if freq_config["frequency"] == "daily" and not include_lagged_controls:
        st.info(
            "ℹ️ Daily data often has strong day-of-week effects. The 7-day lag option can help compare the "
            "same day of week, but it also increases feature count and model reliability risk. Use rolling-origin "
            "validation to decide whether it improves the model."
        )

    # -------------------------------------------------------------------------
    # 4. Validation Summary (compact card before the run button)
    # -------------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### Validation Summary")

    test_regions = st.session_state.selected_experiment_regions
    control_regions = st.session_state.final_controls[geo_col].tolist()
    n_test = len(test_regions)
    n_control = len(control_regions)

    # ---- Observed period counts (preferred over calendar-span estimates) ----
    # Reuses the _observed_period_count() helper defined earlier in this function (section 1c),
    # which is based on the actual dates present for the selected KPI.
    if mode == "Design":
        hist_periods = _observed_period_count(pre_start, pre_end)
        test_length = None
        placebo_len = placebo_length_periods
    else:
        hist_periods = _observed_period_count(pre_start, pre_end)
        test_length = _observed_period_count(test_start, test_end)
        placebo_len = None

    with st.container(border=True):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("KPI", selected_metric)
        col2.metric("Test regions", n_test)
        col3.metric("Control regions", n_control)
        col4.metric("Analysis type", selected_label)

        col5, col6, col7 = st.columns(3)
        col5.metric(
            f"Historical period (observed {freq_config['period_label_plural']})", hist_periods
        )
        if mode == "Design":
            col6.metric(
                f"Simulated test length ({freq_config['period_label_plural']})", placebo_len
            )
            col7.empty()
        else:
            col6.metric(f"Test period (observed {freq_config['period_label_plural']})", test_length)
            col7.metric("Post‑test included", "Yes" if use_post else "No")

    # ---- Daily short-history caution (does not block the user) ----
    if freq_config["frequency"] == "daily" and hist_periods is not None:
        _horizon_for_check = (
            placebo_length_periods
            if placebo_length_periods is not None
            else freq_config["default_validation_horizon_periods"]
        )
        _est_folds = hist_periods - min_training_periods - _horizon_for_check + 1
        if hist_periods < 84:
            st.warning(
                "⚠️ Daily data with fewer than around 12 weeks of pre-period history may produce unstable "
                "validation and placebo results. Treat model reliability risk, rolling-origin metrics and placebo "
                "ranges with caution."
            )
        elif _est_folds < 5:
            st.warning(
                "⚠️ With the current minimum training period and window length, rolling-origin validation is "
                "likely to produce very few folds. Treat model reliability risk, rolling-origin metrics and placebo "
                "ranges with caution, or consider a longer pre-period / shorter window."
            )

    # -------------------------------------------------------------------------
    # 4b. Tracking-outage / data-quality period exclusion — persists across
    # reruns and the Run button click (options never depend on this widget's
    # own current selection, so a previously-selected exclusion can't be
    # silently dropped by Streamlit on a later rerun). Applied once to
    # agg_df_val inside the Run handler below, so validation, evaluation, and
    # Bayesian TBR all share the exact same retained dates (they all read
    # from the one agg_df_val stored in st.session_state.validation_results).
    # -------------------------------------------------------------------------
    _ts_metric_df = df_long[df_long["metric_name"] == selected_metric]
    _ts_wide = _ts_metric_df.pivot_table(
        index="region_raw", columns="date", values="kpi", aggfunc="sum"
    )
    _ts_quality_report = compute_period_quality(_ts_wide)
    _ts_reason_by_date = {
        row.date: "; ".join(row.reasons) for row in _ts_quality_report.rows if row.reasons
    }
    _ts_auto_flagged_dates = set(_ts_quality_report.definite_outage_dates) | set(
        _ts_quality_report.missing_period_dates
    )
    _ts_date_option_labels = []
    _ts_label_to_date = {}
    for _d in sorted(_ts_wide.columns):
        _d = pd.Timestamp(_d)
        _reason = _ts_reason_by_date.get(_d)
        _label = f"{_d.strftime('%d %b %y')} — {_reason}" if _reason else _d.strftime("%d %b %y")
        _ts_date_option_labels.append(_label)
        _ts_label_to_date[_label] = _d

    _ts_exclude_widget_key = f"{mode_prefix}_outage_exclude_select"
    if _ts_exclude_widget_key not in st.session_state:
        st.session_state[_ts_exclude_widget_key] = [
            lbl for lbl, d in _ts_label_to_date.items() if d in _ts_auto_flagged_dates
        ]
    st.markdown("**Periods to exclude because of tracking or data-quality issues:**")
    _ts_selected_exclude_labels = st.multiselect(
        "kpi_outage_exclude",
        _ts_date_option_labels,
        label_visibility="collapsed",
        help=(
            "Dates that look like a market-wide tracking outage (all or almost all "
            "regions exactly zero, or most regions missing) are preselected. This "
            "exclusion is shared by validation, evaluation, and Bayesian TBR for this "
            "uploaded file."
        ),
        key=_ts_exclude_widget_key,
    )
    _ts_manual_excluded_dates = {_ts_label_to_date[lbl] for lbl in _ts_selected_exclude_labels}

    _ts_planned_test_dates = (
        {
            pd.Timestamp(d)
            for d in _ts_wide.columns
            if pd.Timestamp(test_start) <= pd.Timestamp(d) <= pd.Timestamp(test_end)
        }
        if test_start is not None and test_end is not None
        else set()
    )
    _ts_excluded_test_dates = _ts_manual_excluded_dates & _ts_planned_test_dates
    _ts_test_exclusion_share = (
        len(_ts_excluded_test_dates) / len(_ts_planned_test_dates)
        if _ts_planned_test_dates
        else 0.0
    )
    _ts_test_guard_triggered = _ts_test_exclusion_share > 0.20
    _ts_test_guard_override_key = f"{mode_prefix}_test_exclusion_override"
    if _ts_test_guard_triggered:
        st.warning(
            f"⚠️ {len(_ts_excluded_test_dates)} of {len(_ts_planned_test_dates)} planned test "
            f"period(s) ({_ts_test_exclusion_share:.0%}) are excluded as tracking-outage/"
            "data-quality periods. Uplift would be estimated only over the remaining "
            "analysed periods."
        )
        _ts_test_guard_override = st.checkbox(
            "Advanced: run anyway despite the excluded test-period share above 20%",
            value=False,
            key=_ts_test_guard_override_key,
        )
    else:
        _ts_test_guard_override = st.session_state.get(_ts_test_guard_override_key, False)

    if _ts_manual_excluded_dates:
        st.caption(
            f"ℹ️ {len(_ts_manual_excluded_dates)} period(s) excluded from the analysis below "
            f"({len(_ts_auto_flagged_dates)} auto-flagged)."
        )

    # -------------------------------------------------------------------------
    # 5. Run button
    # -------------------------------------------------------------------------
    run_label = "Assess Region Alignment" if mode == "Design" else "Evaluate Test Impact"
    _freq_mismatch_blocked = st.session_state.get("frequency_mismatch_blocked", False)
    _run_disabled = insufficient_pre_period or _freq_mismatch_blocked
    if _freq_mismatch_blocked:
        _run_help = "Resolve or acknowledge the frequency mismatch warning above before running."
    elif insufficient_pre_period:
        _run_help = "Resolve the pre-period data warning above before running."
    else:
        _run_help = None
    validate_clicked = st.button(
        run_label,
        width="stretch",
        type="primary",
        key=f"{mode_prefix}_run_button",
        disabled=_run_disabled,
        help=_run_help,
    )

    if validate_clicked:
        st.session_state.validation_triggered = True

    # -------------------------------------------------------------------------
    # Process validation if triggered — IDENTICAL to working file
    # -------------------------------------------------------------------------
    if st.session_state.validation_triggered:
        # ---- Data-quality gate: blocking errors prevent modelling; warnings
        # (which never populate blocking_errors) do not. ----
        _quality_blockers = _quality_blocking_errors()
        if _quality_blockers:
            for _qb in _quality_blockers:
                st.error(f"🚫 {_qb}")
            st.session_state.validation_triggered = False
            st.stop()
        if (
            uploaded_file is None and st.session_state.get("kpi_regional_dataset") is None
        ) or st.session_state.kpi_long_df is None:
            st.error("KPI file not available. Please upload a file first.")
            st.session_state.validation_triggered = False
            st.stop()
        if st.session_state.get("frequency_mismatch_blocked", False):
            st.error(
                "Validation cannot run while there is an unacknowledged frequency mismatch. Please resolve or acknowledge it above."
            )
            st.session_state.validation_triggered = False
            st.stop()

        if insufficient_pre_period:
            st.error(
                "Not enough pre-period observations for the selected minimum training period and "
                "validation window. Choose a longer pre-period, shorter validation window, or switch to "
                "weekly aggregation."
            )
            st.session_state.validation_triggered = False
            st.stop()

        if _ts_test_guard_triggered and not _ts_test_guard_override:
            st.error(
                f"{len(_ts_excluded_test_dates)} of {len(_ts_planned_test_dates)} planned test "
                f"period(s) ({_ts_test_exclusion_share:.0%}) are excluded as tracking-outage/"
                "data-quality periods — above the 20% guard threshold. Repair/reupload the data, "
                "exclude fewer test-period dates, or enable the advanced override above to "
                "proceed anyway."
            )
            st.session_state.validation_triggered = False
            st.stop()

        with st.spinner("Running validation models..."):
            # ---- adobe_to_geo (raw Adobe Analytics name -> canonical geo_col name) only
            # applies to the demographic/structural workflow, where uploaded KPI files may
            # use different region spellings than the built-in population dataset. In KPI
            # Pattern mode there's no such file to map against — the uploaded file's
            # aggregation-level values ARE the canonical geo_col values already (that's
            # what Region Matching built them from), so direct-match is sufficient. ----
            if st.session_state.get("kpi_pattern_mode"):
                adobe_to_geo = {}
            else:
                try:
                    master_df = load_market_sheet(DATA_PATH, market, _workbook_identity_tuple())
                    adobe_to_geo = dict(
                        zip(
                            master_df[ADOBE_COL].astype(str).str.strip(),
                            master_df[geo_col].astype(str).str.strip(),
                        )
                    )
                except Exception as e:
                    st.error(f"Failed to load region mapping: {e}")
                    st.stop()

            test_regions_val = st.session_state.selected_experiment_regions
            control_regions_val = st.session_state.final_controls[geo_col].tolist()
            force_excluded_regions = st.session_state.get("force_ctrl_exclude", [])
            if not isinstance(force_excluded_regions, list):
                force_excluded_regions = []

            df_long_metric = df_long[df_long["metric_name"] == selected_metric].copy()
            if df_long_metric.empty:
                st.error(f"No data for selected metric: {selected_metric}")
                st.stop()

            df_long_raw = df_long_metric.copy()
            # ---- Full candidate universe (every region GeoMatch knows about), NOT just
            # test+selected-control — see build_region_mapping()'s docstring for why this
            # matters: passing a smaller set here silently caps what "Data-Optimised
            # Controls" can search over. ----
            valid_regions_for_mapping = sorted(
                set(agg_df[geo_col].dropna().astype(str).str.strip().unique().tolist())
                | set(test_regions_val)
                | set(control_regions_val)
            )
            df_long_mapped = build_region_mapping(
                df_long_raw, valid_regions_for_mapping, adobe_to_geo
            )
            # Persist the mapping-quality report (raw/mapped/unmapped regions +
            # unmapped rows for download) so the data-quality UI can show it.
            st.session_state.kpi_mapping_report = compute_mapping_report(df_long_mapped)
            matched = df_long_mapped[df_long_mapped["region"].notna()]
            if matched.empty:
                st.error("No regions matched. Check mapping table.")
                st.stop()

            agg_df_val = apply_geo_aggregation(matched, geo_col)
            if agg_df_val.empty:
                st.error("Aggregation resulted in empty dataset.")
                st.stop()

            # Apply the shared tracking-outage/data-quality exclusion (section 4b above) —
            # the same retained dates are then used by validation, evaluation, and Bayesian
            # TBR, since they all read this stored agg_df_val.
            if _ts_manual_excluded_dates:
                agg_df_val = agg_df_val[~agg_df_val["date"].isin(_ts_manual_excluded_dates)]
                if agg_df_val.empty:
                    st.error("No data remains after excluding flagged/selected periods.")
                    st.stop()

            # Region Mapping Diagnostics (unchanged)
            with st.expander("Region Mapping Diagnostics"):
                raw_count = len(df_long_raw["region_raw"].unique())
                matched_count = len(matched["region"].unique())
                unmatched_count = len(
                    df_long_raw[~df_long_raw["region_raw"].isin(matched["region_raw"].unique())][
                        "region_raw"
                    ].unique()
                )
                agg_count = len(agg_df_val["region"].unique())
                unmatched_names = (
                    ", ".join(
                        df_long_raw[
                            ~df_long_raw["region_raw"].isin(matched["region_raw"].unique())
                        ]["region_raw"]
                        .unique()
                        .tolist()
                    )
                    if unmatched_count > 0
                    else "None"
                )
                diag_data = {
                    "Metric": [
                        "Raw geographies in KPI file",
                        "Matched to aggregation level",
                        "Unmatched",
                        "Aggregated geographies",
                        "Unmatched names",
                    ],
                    "Value": [
                        str(raw_count),
                        str(matched_count),
                        str(unmatched_count),
                        str(agg_count),
                        unmatched_names,
                    ],
                }
                st.dataframe(pd.DataFrame(diag_data), width="stretch", hide_index=True)

                all_regions = sorted(agg_df_val["region"].unique())
                role_rows = []
                for region in all_regions:
                    if region in test_regions_val:
                        m1_role = "Test Region"
                    elif region in force_excluded_regions:
                        m1_role = "Force-Excluded Region"
                    elif region in control_regions_val:
                        m1_role = "Matched Control Region"
                    else:
                        m1_role = "Unused Candidate Region"

                    if region in test_regions_val:
                        m2_role = "Test Region"
                    else:
                        m2_role = "Control Candidate Region"

                    if force_excluded_regions:
                        if region in test_regions_val:
                            m3_role = "Test Region"
                        elif region in force_excluded_regions:
                            m3_role = "Force-Excluded Region"
                        else:
                            m3_role = "Control Candidate Region"
                    else:
                        m3_role = None

                    row = {
                        "Region": region,
                        "Method 1 (Structurally Matched)": m1_role,
                        "Method 2 (Data-Optimised)": m2_role,
                    }
                    if force_excluded_regions:
                        row["Method 3 (Data-Optimised Excl.)"] = m3_role
                    role_rows.append(row)

                role_df = pd.DataFrame(role_rows)

                def color_roles(val):
                    if val == "Test Region":
                        return "background-color: #90EE90"
                    elif val == "Matched Control Region":
                        return "background-color: #FFFACD"
                    elif val == "Control Candidate Region":
                        return "background-color: #ADD8E6"
                    elif val == "Force-Excluded Region":
                        return "background-color: #FFCCCB"
                    elif val == "Unused Candidate Region":
                        return "background-color: #D3D3D3"
                    else:
                        return ""

                role_cols = [c for c in role_df.columns if c != "Region"]
                styled_role = role_df.style.map(color_roles, subset=role_cols)
                st.dataframe(styled_role, width="stretch", hide_index=True)

            # Regional KPI Summary (unchanged)
            st.subheader("KPI Performance by Geography")
            summary_start = pd.Timestamp(pre_start)
            summary_end = pd.Timestamp(pre_end)
            summary_df = agg_df_val[
                (agg_df_val["date"] >= summary_start) & (agg_df_val["date"] <= summary_end)
            ].copy()
            n_periods = summary_df["date"].nunique()
            st.caption(
                f"{summary_label}:  "
                f"⏱️ {n_periods} {freq_config['period_label_plural']}  |  "
                f"📅 {summary_start:%d %b %Y} – {summary_end:%d %b %Y}"
            )
            if n_periods == 0:
                st.warning("No data available in the selected date range.")
            else:
                region_stats = []
                total_kpi = summary_df["kpi"].sum()
                kpi_name = selected_metric
                for region in sorted(summary_df["region"].unique()):
                    region_data = summary_df[summary_df["region"] == region]
                    total = region_data["kpi"].sum()
                    avg = region_data["kpi"].mean()
                    std = region_data["kpi"].std()
                    cv = std / avg if avg != 0 else np.nan
                    if cv < 0.2:
                        vol_flag = "Low"
                    elif cv < 0.5:
                        vol_flag = "Medium"
                    else:
                        vol_flag = "High"
                    status = (
                        "Test Region"
                        if region in test_regions_val
                        else (
                            "Matched Control Region"
                            if region in control_regions_val
                            else (
                                "Force-Excluded Region"
                                if region in force_excluded_regions
                                else "Unused Candidate Region"
                            )
                        )
                    )
                    region_stats.append(
                        {
                            "Region": region,
                            "Status": status,
                            f"Total {kpi_name}": total,
                            "Share (%)": (total / total_kpi) * 100 if total_kpi > 0 else 0,
                            f"Avg. {kpi_name} per {freq_config['period_label_singular']}": avg,
                            "Std dev": std,
                            "Coefficient of Variation": cv,
                            "Volatility": vol_flag,
                        }
                    )
                desc_df = pd.DataFrame(region_stats)

                def color_status(val):
                    if val == "Test Region":
                        return "background-color: #90EE90"
                    elif val == "Matched Control Region":
                        return "background-color: #FFFACD"
                    elif val == "Force-Excluded Region":
                        return "background-color: #FFCCCB"
                    else:
                        return "background-color: #D3D3D3"

                styled_desc = desc_df.style.format(
                    {
                        f"Total {kpi_name}": "{:,.0f}",
                        "Share (%)": "{:.1f}%",
                        f"Avg. {kpi_name} per {freq_config['period_label_singular']}": "{:.1f}",
                        "Std dev": lambda x: f"±{x:.1f}",
                        "Coefficient of Variation": "{:.3f}",
                    }
                ).map(color_status, subset=["Status"])
                st.dataframe(styled_desc, width="stretch")

            # -------------------------------------------------------------
            # 7. Run validation methods — IDENTICAL to working file
            # -------------------------------------------------------------
            st.subheader("Validation Results")
            results = {}

            method1_key = (
                METHOD_USER_SELECTED
                if st.session_state.get("user_selected_mode", False)
                else METHOD_STRUCTURAL
            )

            with st.spinner(f"Running {method1_key}..."):
                res1 = run_validation_method(
                    agg_df_val,
                    control_regions_val,
                    test_regions_val,
                    "enet",
                    pre_start,
                    pre_end,
                    test_start,
                    test_end,
                    use_post,
                    post_start,
                    post_end,
                    compute_uplift=compute_uplift,
                    placebo_length_periods=placebo_length_periods,
                    min_training_periods=min_training_periods,
                    include_lagged_controls=st.session_state.get("include_lagged_controls", False),
                    frequency_config=freq_config,
                )
                if res1 is None:
                    st.error(f"{method1_key} failed: insufficient pre‑period data.")
                else:
                    results[method1_key] = res1

            all_non_test = sorted(
                [r for r in agg_df_val["region"].unique() if r not in test_regions_val]
            )
            if len(all_non_test) < 2:
                st.warning(
                    "Not enough non‑test regions for Data-Optimised Controls. Method 2 skipped."
                )
            else:
                with st.spinner("Running Data-Optimised Controls..."):
                    res2 = run_validation_method(
                        agg_df_val,
                        all_non_test,
                        test_regions_val,
                        "lasso",
                        pre_start,
                        pre_end,
                        test_start,
                        test_end,
                        use_post,
                        post_start,
                        post_end,
                        compute_uplift=compute_uplift,
                        placebo_length_periods=placebo_length_periods,
                        min_training_periods=min_training_periods,
                        include_lagged_controls=st.session_state.get(
                            "include_lagged_controls", False
                        ),
                        frequency_config=freq_config,
                    )
                    if res2 is not None:
                        results[METHOD_DATA_OPTIMISED] = res2

            force_excluded_in_agg = [
                r for r in force_excluded_regions if r in agg_df_val["region"].unique()
            ]
            if force_excluded_regions and force_excluded_in_agg:
                candidate_controls = [r for r in all_non_test if r not in force_excluded_in_agg]
                if len(candidate_controls) < 2:
                    st.warning(
                        "Not enough non‑test regions after Excluding Force-Exclude Regions. Method 3 skipped."
                    )
                else:
                    with st.spinner(
                        "Running Data-Optimised Controls (Excluding Force-Exclude Regions)..."
                    ):
                        res3 = run_validation_method(
                            agg_df_val,
                            candidate_controls,
                            test_regions_val,
                            "lasso",
                            pre_start,
                            pre_end,
                            test_start,
                            test_end,
                            use_post,
                            post_start,
                            post_end,
                            compute_uplift=compute_uplift,
                            placebo_length_periods=placebo_length_periods,
                            min_training_periods=min_training_periods,
                            include_lagged_controls=st.session_state.get(
                                "include_lagged_controls", False
                            ),
                            frequency_config=freq_config,
                        )
                        if res3 is not None:
                            results[METHOD_DATA_OPTIMISED_EXCL] = res3
            elif force_excluded_regions and not force_excluded_in_agg:
                st.warning(
                    "Force‑excluded regions were defined but none appear in the aggregated dataset. Check region names. Skipping Method 3."
                )
            else:
                st.info(
                    "No force‑excluded regions were defined, so Method 3 (excluding them) was not run."
                )

            st.session_state.validation_results = {
                "results": results,
                "agg_df": agg_df_val,
                "test_regions": test_regions_val,
                "control_regions": control_regions_val,
                "force_excluded": force_excluded_regions,
                "mode": mode,
                "pre_start": pre_start,
                "pre_end": pre_end,
                "test_start": test_start,
                "test_end": test_end,
                "use_post": use_post,
                "post_start": post_start,
                "post_end": post_end,
                "selected_metric": selected_metric,
                "placebo_length_periods": placebo_length_periods,
                "placebo_length_weeks": placebo_length_periods,  # backward-compatible alias
                "min_training_periods": min_training_periods,
                "min_training_weeks": min_training_periods,  # backward-compatible alias
                "include_lagged_controls": include_lagged_controls,
                "time_series_frequency": time_series_frequency,
                "frequency_config": freq_config,
                "automatic_outage_dates": sorted(_ts_auto_flagged_dates),
                "manual_excluded_dates": sorted(_ts_manual_excluded_dates),
                "effective_excluded_dates": sorted(_ts_manual_excluded_dates),
                "planned_test_periods": len(_ts_planned_test_dates),
                "analysed_test_periods": len(_ts_planned_test_dates) - len(_ts_excluded_test_dates),
                "test_exclusion_guard_overridden": bool(
                    _ts_test_guard_triggered and _ts_test_guard_override
                ),
            }

            # ---- Experiment record: store the validation inputs and stamp the
            # counterfactual_validation stage (Stage 4). ----
            st.session_state.experiment_validation_inputs = {
                "kpi_file_name": kpi_file_name,
                "kpi_file_size": kpi_file_size,
                "selected_metric": selected_metric,
                "kpi_agg_col": _kpi_agg_col,
                "time_series_frequency": time_series_frequency,
                "pre_start": _iso_date(pre_start),
                "pre_end": _iso_date(pre_end),
                "test_start": _iso_date(test_start),
                "test_end": _iso_date(test_end),
                "use_post": bool(use_post),
                "post_start": _iso_date(post_start),
                "post_end": _iso_date(post_end),
                "manual_excluded_dates": sorted(_iso_date(d) for d in _ts_manual_excluded_dates),
                "auto_flagged_dates": sorted(_iso_date(d) for d in _ts_auto_flagged_dates),
                "include_lagged_controls": include_lagged_controls,
                "min_training_periods": min_training_periods,
                "placebo_length_periods": placebo_length_periods,
            }
            _stamp_validation_stage()

            st.session_state.validation_triggered = False

    # -------------------------------------------------------------------------
    # Display results if they exist — IDENTICAL to working file
    # -------------------------------------------------------------------------
    if st.session_state.validation_results is not None:
        vres = st.session_state.validation_results
        # Only show results if they match the current mode
        if vres.get("mode") != mode:
            st.info("Results from a previous run are shown. Re-run to update for the current mode.")
            return
        results = vres["results"]
        agg_df_val = vres["agg_df"]
        test_regions_val = vres["test_regions"]
        control_regions_val = vres["control_regions"]
        force_excluded_regions = vres["force_excluded"]
        pre_start = vres["pre_start"]
        pre_end = vres["pre_end"]
        test_start = vres["test_start"]
        test_end = vres["test_end"]
        use_post = vres["use_post"]
        post_start = vres["post_start"]
        post_end = vres["post_end"]
        selected_metric = vres["selected_metric"]
        placebo_length_periods = vres.get(
            "placebo_length_periods", vres.get("placebo_length_weeks")
        )
        min_training_periods = vres.get("min_training_periods", vres.get("min_training_weeks", 13))
        include_lagged_controls_val = vres.get("include_lagged_controls", False)
        vres_time_series_frequency = vres.get("time_series_frequency", "weekly")
        vres_freq_config = vres.get("frequency_config") or get_frequency_config(
            vres_time_series_frequency
        )
        all_non_test = sorted(
            [r for r in agg_df_val["region"].unique() if r not in test_regions_val]
        )

        if include_lagged_controls_val:
            _same_period_word = "day" if vres_freq_config["frequency"] == "daily" else "week"
            st.caption(
                f"⏱️ {vres_freq_config['lag_label']} lagged controls are **enabled** — models were fit on "
                f"same-{_same_period_word} and lagged control features."
            )

        # ---- Display per‑method results ----
        for method_name, res in results.items():
            st.markdown(f"#### {method_name}")
            if method_name == METHOD_STRUCTURAL:
                st.caption(
                    "Structurally Matched Controls uses the GeoMatch-selected control pool, then fits an "
                    "Elastic Net model to estimate the counterfactual. Some structurally selected controls "
                    "may be shrunk to zero by the model."
                )

            with st.expander("Control Selection Details", expanded=False):
                if method_name in [METHOD_STRUCTURAL, METHOD_USER_SELECTED]:
                    st.write(f"**Candidate controls:** {res['n_candidates']}")
                    st.write(f"**Selected controls:** {res['n_selected']}")
                    st.write(f"**Removed controls:** {res['n_removed']}")
                    if res.get("include_lagged_controls"):
                        st.caption(
                            f"Model features used ({len(res.get('model_feature_cols', []))}): includes same-period and lagged control terms."
                        )
                    if not res["selected_df"].empty:
                        st.dataframe(res["selected_df"], width="stretch")
                    else:
                        st.write("**Control regions:**", ", ".join(control_regions_val))
                else:
                    st.write(f"**Candidate controls:** {res['n_candidates']}")
                    st.write(f"**Selected controls:** {res['n_selected']}")
                    st.write(f"**Removed controls:** {res['n_removed']}")
                    if res.get("include_lagged_controls"):
                        st.caption(
                            f"Model features used ({len(res.get('model_feature_cols', []))}): includes same-period and lagged control terms."
                        )
                    if res["n_selected"] > 0:
                        st.dataframe(res["selected_df"])
                    else:
                        st.warning("LASSO selected zero controls.")
                    st.caption(f"Model regularisation strength (alpha): {res['alpha']:.6f}")

            _lag_drop_meta = res.get("lag_drop_metadata")
            if (
                res.get("include_lagged_controls")
                and res.get("time_series_frequency") == "daily"
                and _lag_drop_meta
            ):
                if _lag_drop_meta.get("lag_drop_pct", 0) > 20:
                    st.warning(
                        f"⚠️ Daily 7-day lagged controls require matching dates exactly 7 calendar days earlier. "
                        f"{_lag_drop_meta['rows_dropped_due_to_lag']} of {_lag_drop_meta['rows_before_lag_drop']} rows "
                        f"({_lag_drop_meta['lag_drop_pct']:.1f}%) were dropped because those lag dates were missing. "
                        f"Check whether your daily data has gaps."
                    )

            # ---- High validation error, even when the overfitting gap is small (item 13) ----
            _rolling_smape_mean = res.get(
                "rolling_smape_mean", res.get("holdout_smape_mean", np.nan)
            )
            if _rolling_smape_mean is not None and not (
                isinstance(_rolling_smape_mean, float) and np.isnan(_rolling_smape_mean)
            ):
                if _rolling_smape_mean > 30:
                    st.error(
                        f"High validation error: rolling-origin sMAPE is {_rolling_smape_mean:.1f}%. "
                        "Even if the Overfitting Gap is small, the model is not predicting the test group accurately enough to support a reliable uplift estimate."
                    )
                elif _rolling_smape_mean > 20:
                    st.warning(
                        f"Elevated validation error: rolling-origin sMAPE is {_rolling_smape_mean:.1f}%. "
                        "Review the fit chart, residual diagnostics, and placebo results before relying on this method."
                    )

            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Pre-Period Correlation",
                f"{res['corr']:.3f}",
                help="How closely the counterfactual fits the actual test KPI during the pre‑period. This is an in‑sample measure.",
            )
            col2.metric(
                "Pre-Period R²",
                f"{res['r2']:.3f}",
                help="Proportion of variation in the test KPI explained by the controls. This is an in‑sample measure.",
            )
            col3.metric(
                "Pre-Period sMAPE",
                f"{res['smape']:.1f}%",
                help="Average percentage error in pre‑period predictions (in‑sample). Lower is better.",
            )

            if (
                compute_uplift
                and test_start is not None
                and test_end is not None
                and res["uplift"] is not None
            ):
                st.metric(
                    "Observed Uplift",
                    f"{res['uplift']:.0f} ({res['uplift_pct']:.1f}%)",
                    help="Absolute uplift = Actual sum − Predicted baseline sum. Percentage = uplift / baseline.",
                )

            with st.expander("Rolling Cross-Validation", expanded=False):
                _res_freq_config = res.get("frequency_config") or vres_freq_config
                _period_word = _res_freq_config["period_label_singular"]
                _period_word_plural = _res_freq_config["period_label_plural"]
                _vw = res.get(
                    "validation_window_periods",
                    res.get("validation_window_weeks", placebo_length_periods),
                )
                _mt = res.get(
                    "min_training_periods", res.get("min_training_weeks", min_training_periods)
                )
                st.caption(
                    f"Rolling-origin validation used a **{_vw}-{_period_word}** forecast horizon "
                    f"and required at least **{_mt} {_period_word_plural}** of training history before each validation window."
                )
                _rcv_col1 = st.columns(1)[0]
                _rcv_col1.metric(
                    "Average Out-of-Sample sMAPE",
                    f"{res['holdout_smape_mean']:.1f}%"
                    if not np.isnan(res["holdout_smape_mean"])
                    else "-",
                    help="Average sMAPE across all rolling-origin validation windows. Out-of-sample — more reliable than pre-period fit.",
                )
                _fold_df = res.get("rolling_origin_folds", pd.DataFrame())
                if not _fold_df.empty:
                    _display_cols = [
                        "fold_number",
                        "training_periods",
                        "forecast_horizon_periods",
                        "test_start_date",
                        "test_end_date",
                        "smape",
                        "rmse",
                        "bias_pct",
                        "uplift_error_pct",
                    ]
                    _display_cols = [c for c in _display_cols if c in _fold_df.columns]
                    _fold_display = _fold_df[_display_cols].copy()
                    # Format dates as DD/MM/YYYY
                    for _date_col in ["test_start_date", "test_end_date"]:
                        if _date_col in _fold_display.columns:
                            _fold_display[_date_col] = pd.to_datetime(
                                _fold_display[_date_col]
                            ).dt.strftime("%d/%m/%Y")
                    # Format percentage columns
                    for _pct_col in ["smape", "bias_pct", "uplift_error_pct"]:
                        if _pct_col in _fold_display.columns:
                            _fold_display[_pct_col] = _fold_display[_pct_col].apply(
                                lambda v: f"{v:.1f}%" if pd.notna(v) else "-"
                            )
                    if "rmse" in _fold_display.columns:
                        _fold_display["rmse"] = _fold_display["rmse"].apply(
                            lambda v: f"{v:.0f}" if pd.notna(v) else "-"
                        )
                    # Rename to human-readable labels
                    _training_periods_label = f"Training {_period_word_plural.capitalize()}"
                    _horizon_label = (
                        "Horizon (Days)"
                        if _res_freq_config["frequency"] == "daily"
                        else "Horizon (Wks)"
                    )
                    _fold_display.rename(
                        columns={
                            "fold_number": "Fold",
                            "training_periods": _training_periods_label,
                            "forecast_horizon_periods": _horizon_label,
                            "test_start_date": "Forecast Start",
                            "test_end_date": "Forecast End",
                            "smape": "sMAPE",
                            "rmse": "RMSE",
                            "bias_pct": "Bias %",
                            "uplift_error_pct": "Uplift Error %",
                        },
                        inplace=True,
                    )
                    st.dataframe(_fold_display, width="stretch", hide_index=True)
                else:
                    st.info(
                        "No rolling-origin folds were generated — the historical period may be too short for the selected training and window settings."
                    )

            plot_type = st.radio(
                "Display plot:",
                ["Actual", "Indexed (pre‑period avg = 100)"],
                horizontal=True,
                key=f"plot_toggle_{mode_prefix}_{method_name}",
            )

            all_dates = (
                res["dates_pre"]
                + (res["dates_test"] if res["dates_test"] else [])
                + (res["dates_post"] if res["dates_post"] else [])
            )
            all_actual = (
                list(res["y_pre"])
                + (list(res["y_test_actual"]) if res["y_test_actual"] is not None else [])
                + (list(res["y_post_actual"]) if res["y_post_actual"] is not None else [])
            )
            all_pred = (
                list(res["y_pred_pre"])
                + (list(res["y_pred_test"]) if res["y_pred_test"] is not None else [])
                + (list(res["y_post_pred"]) if res["y_post_pred"] is not None else [])
            )

            if plot_type == "Actual":
                y_actual = all_actual
                y_pred = all_pred
                y_label = selected_metric
                title_suffix = "Actual"
            else:
                pre_mean = np.mean(res["y_pre"])
                if pre_mean > 0:
                    y_actual = np.array(all_actual) / pre_mean * 100
                    y_pred = np.array(all_pred) / pre_mean * 100
                    y_label = f"{selected_metric} (Indexed)"
                    title_suffix = "Indexed (pre‑period avg=100)"
                else:
                    st.warning("Pre‑period average zero, cannot index. Showing Actual.")
                    y_actual = all_actual
                    y_pred = all_pred
                    y_label = selected_metric
                    title_suffix = "Actual"

            plot_df = pd.DataFrame(
                {"Date": all_dates, "Actual": y_actual, "Predicted / Counterfactual": y_pred}
            ).melt(id_vars="Date", var_name="Series", value_name="Value")

            fig = px.line(
                plot_df,
                x="Date",
                y="Value",
                color="Series",
                title=f"{title_suffix} – {method_name}",
                labels={"Value": y_label, "Date": "Date"},
            )

            def add_vline_with_annotation(fig, x_val, color, label, position="top left"):
                if x_val is None:
                    return
                fig.add_vline(
                    x=x_val,
                    line_dash="dash",
                    line_color=color,
                    annotation_text=label,
                    annotation_position=position,
                )

            if compute_uplift and test_start is not None:
                add_vline_with_annotation(fig, test_start, "red", "Test start", position="top left")
                add_vline_with_annotation(fig, test_end, "orange", "Test end", position="top right")

            fig.update_layout(yaxis_title=y_label)
            st.plotly_chart(fig, width="stretch")

            # ---- Data export (xlsx): Plotly's own modebar only exports a PNG snapshot
            # of the chart, not the underlying data, so this is a separate download
            # button. Independent of whichever plot_type is currently toggled above —
            # always includes both an "Actual" sheet and an "Indexed" sheet computed
            # fresh here, so the export doesn't depend on the user's current toggle
            # selection. ----
            _actual_export_df = pd.DataFrame(
                {
                    "Date": all_dates,
                    "Actual": all_actual,
                    "Predicted / Counterfactual": all_pred,
                }
            )
            _pre_mean_export = np.mean(res["y_pre"])
            if _pre_mean_export > 0:
                _indexed_export_df = pd.DataFrame(
                    {
                        "Date": all_dates,
                        "Actual": np.array(all_actual) / _pre_mean_export * 100,
                        "Predicted / Counterfactual": np.array(all_pred) / _pre_mean_export * 100,
                    }
                )
            else:
                _indexed_export_df = None
            st.download_button(
                "⬇️ Download chart data (.xlsx)",
                data=build_chart_data_xlsx(
                    {
                        "Actual": _actual_export_df,
                        "Indexed (pre-period avg=100)": _indexed_export_df,
                    }
                ),
                file_name=f"{method_name}_{title_suffix.split(' ')[0].lower()}_chart_data.xlsx".replace(
                    " ", "_"
                ),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"download_chart_data_{mode_prefix}_{method_name}",
            )

        # ---- Method Comparison table (traffic-light diagnostics), captions, and
        # interpretation help — rendered by a standalone, independently testable function. ----
        render_method_comparison_table(results, mode, test_start, control_regions_val)

        # ---- Power analysis / Minimum Detectable Effect (Design mode only) ----
        # Reuses each method's placebo (fake-test) uplift distribution: injecting a
        # synthetic +/- x% effect into a placebo window shifts its measured uplift-%
        # in closed form (the model fit is unaffected, because training data precedes
        # the window), so power at each effect size is computed with zero refitting.
        # See compute_power_curve() for the math and caveats.
        if mode == "Design":
            st.subheader("Test Sensitivity — What Size of Effect Can This Design Detect?")
            _first_res = next(iter(results.values()), {})
            _p_len = _first_res.get("placebo_length_periods")
            _p_unit = freq_config["period_label_singular"]
            _test_len_phrase = f"a {_p_len}-{_p_unit} test" if _p_len else "a test of this length"
            st.caption(
                f"This answers one planning question: **how big would a real effect need to be for "
                f"{_test_len_phrase} to reliably spot it?** "
                "We take the fake-test windows from above (where nothing actually happened), add a pretend uplift of a "
                "given size to each, and count how often the design would have flagged it as a real effect. The "
                '"minimum detectable effect" (MDE) is the smallest effect the design catches at least 80% of the '
                "time. Rule of thumb: only run the test if the effect you're realistically hoping for is at least "
                "this big — otherwise a real effect will likely be lost in the noise. "
                "*(For technical readers: an empirical power analysis at one-sided \u03b1 = 5%; methodology in the "
                "expander below.)*"
            )
            _power_alpha = 0.05
            _power_target = 0.80
            _power_curves = {}
            _mde_rows = []
            for _m_name, _m_res in results.items():
                _curve = compute_power_curve(_m_res.get("placebo_uplift_pcts"), alpha=_power_alpha)
                if _curve.empty:
                    continue
                _power_curves[_m_name] = _curve
                _n_windows = len(
                    [
                        p
                        for p in (
                            _m_res.get("placebo_uplift_pcts")
                            if _m_res.get("placebo_uplift_pcts") is not None
                            else []
                        )
                        if _is_valid_number(p)
                    ]
                )
                _mde_up = find_mde(_curve, "power_lift", _power_target)
                _mde_dn = find_mde(_curve, "power_drop", _power_target)
                _mde_rows.append(
                    {
                        "Method": _m_name,
                        "Placebo Windows": _n_windows,
                        "Smallest detectable uplift": (
                            f"+{_mde_up:.1f}%" if _mde_up is not None else "> +30%"
                        ),
                        "Smallest detectable decline": (
                            f"-{_mde_dn:.1f}%" if _mde_dn is not None else "< -30%"
                        ),
                    }
                )
            if not _mde_rows:
                st.info(
                    "Not enough fake-test (placebo) windows to estimate this — at least 5 per method are needed. "
                    "Add more pre-period history or shorten the placebo window length, then re-run validation."
                )
            else:
                st.dataframe(
                    pd.DataFrame(_mde_rows),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Placebo Windows": st.column_config.NumberColumn(
                            "Placebo Windows",
                            help=(
                                "Number of fake-test windows used. This is also the resolution limit: "
                                "power estimates move in steps of 1 \u00f7 this number."
                            ),
                        ),
                        "Smallest detectable uplift": st.column_config.TextColumn(
                            "Smallest detectable uplift",
                            help=(
                                "Minimum detectable effect (MDE) at 80% power. Detection = measured uplift-% "
                                "above the 95th percentile of the placebo uplift-% distribution "
                                "(one-sided \u03b1 = 5%)."
                            ),
                        ),
                        "Smallest detectable decline": st.column_config.TextColumn(
                            "Smallest detectable decline",
                            help=(
                                "Minimum detectable effect (MDE) at 80% power. Detection = measured uplift-% "
                                "below the 5th percentile of the placebo uplift-% distribution "
                                "(one-sided \u03b1 = 5%)."
                            ),
                        ),
                    },
                )
                _power_dir = st.radio(
                    "Effect direction",
                    ["Uplift (campaign / launch)", "Decline (media pause)"],
                    horizontal=True,
                    key=f"{mode_prefix}_power_direction",
                    help=(
                        "Which direction of effect to chart. Technical: uplifts are tested one-sided against the "
                        "95th percentile of the placebo uplift-% distribution; declines against the 5th percentile."
                    ),
                )
                _dir_col = "power_lift" if _power_dir.startswith("Uplift") else "power_drop"
                _chart_frames = []
                for _m_name, _curve in _power_curves.items():
                    _chart_frames.append(
                        pd.DataFrame(
                            {
                                "True effect size (%)": _curve["effect_pct"],
                                "Chance of detecting it (power)": _curve[_dir_col],
                                "Method": _m_name,
                            }
                        )
                    )
                _power_chart_df = pd.concat(_chart_frames, ignore_index=True)
                _fig_power = px.line(
                    _power_chart_df,
                    x="True effect size (%)",
                    y="Chance of detecting it (power)",
                    color="Method",
                    range_y=[0, 1.02],
                )
                _fig_power.layout.yaxis.tickformat = ".0%"
                _fig_power.add_hline(
                    y=_power_target,
                    line_dash="dash",
                    line_color="grey",
                    annotation_text=f"{int(_power_target * 100)}% power — reliable detection",
                    annotation_position="top left",
                )
                st.plotly_chart(_fig_power, width="stretch")
                st.download_button(
                    "⬇️ Download power curve data (.xlsx)",
                    data=build_chart_data_xlsx({"Power Curves": _power_chart_df}),
                    file_name="power_analysis_mde.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"{mode_prefix}_download_power_data",
                )
                st.caption(
                    "⚠️ Treat these numbers as a planning guide, not a guarantee. They come from a limited number of "
                    "practice runs on your own history, and they assume the future will be about as noisy as the past."
                )
                with st.expander("How this is calculated (methodology)", expanded=False):
                    st.markdown(
                        '- Each placebo window above is a "fake test" where nothing happened, measured with the '
                        "same actual-vs-counterfactual machinery as a real result in Evaluate mode: uplift = actuals "
                        "minus the model's counterfactual prediction, trained only on data *before* the window.\n"
                        "- A pretend effect of +x% is added to each window's actuals; because the training data "
                        "precedes the window, the model fit is unchanged and the measured uplift shifts in closed "
                        "form — no refitting needed: measured uplift-% = placebo-% \u00d7 (1 + x/100) + x "
                        "(mirror image for declines).\n"
                        '- "Detected" means the shifted uplift-% falls outside the no-effect placebo distribution '
                        "at a one-sided 5% level: beyond its 95th percentile for uplifts, below its 5th percentile "
                        "for declines.\n"
                        "- Power at each effect size = the share of placebo windows that would have been detected; "
                        "the MDE is the smallest effect size with power ≥ 80%.\n"
                        "- Approximations to keep in mind: the same finite set of windows provides both the noise "
                        "threshold and the power estimate; overlapping windows are not fully independent; and "
                        "resolution is limited to roughly 1 ÷ (number of windows)."
                    )


with tab2:
    st.subheader("🔍 Validate Test Design")
    st.caption(
        "Validate whether your selected control regions can reliably predict the test regions before running a live geo-test."
    )
    render_time_series_validation("Design")

with tab7:
    st.subheader("📊 Measure Test Impact")
    st.caption(
        "Estimate the uplift from your completed geo test and compare results against expected historical variation."
    )
    render_time_series_validation("Evaluate")

# =============================================================================
# TAB 4: BAYESIAN TIME-BASED REGRESSION
# =============================================================================
with tab8:
    st.subheader("🧠 Bayesian Time-Based Regression (TBR)")
    st.caption(
        "Run a Bayesian time-based regression on the results from the Measure Test Impact tab."
    )

    if st.session_state.get("bayesian_results") is None and (
        st.session_state.get("validation_results") is None
        or st.session_state.get("validation_results", {}).get("mode") != "Evaluate"
    ):
        st.info(
            "Run an evaluation in the **Measure Test Impact** tab first. The Bayesian model uses those validation results."
        )
    else:
        # Retrieve validation state needed by Bayesian
        if (
            st.session_state.get("validation_results") is not None
            and st.session_state.get("validation_results", {}).get("mode") == "Evaluate"
        ):
            vres = st.session_state.validation_results
            results = vres["results"]
            agg_df_bayes = vres["agg_df"]
            test_regions_val = vres["test_regions"]
            control_regions_val = vres["control_regions"]
            pre_start = vres["pre_start"]
            pre_end = vres["pre_end"]
            test_start = vres["test_start"]
            test_end = vres["test_end"]
            use_post = vres["use_post"]
            post_start = vres["post_start"]
            post_end = vres["post_end"]
            selected_metric = vres["selected_metric"]
            bayes_time_series_frequency = vres.get("time_series_frequency", "weekly")
            bayes_freq_config = vres.get("frequency_config") or get_frequency_config(
                bayes_time_series_frequency
            )
            all_non_test = sorted(
                [r for r in agg_df_bayes["region"].unique() if r not in test_regions_val]
            )

            available_methods = list(results.keys())
            if available_methods:
                selected_bayes_method = st.selectbox(
                    "Select method for Bayesian TBR evaluation",
                    available_methods,
                    help="The selected method's control list will be used for Bayesian uplift estimation.",
                    key="bayes_method_select",
                )
                if selected_bayes_method:
                    res = results.get(selected_bayes_method)
                    if selected_bayes_method in (METHOD_STRUCTURAL, METHOD_USER_SELECTED):
                        # User Selected Test and Control (and the structural pool itself)
                        # uses the user-selected controls directly, but must not be empty.
                        bayes_control_list = control_regions_val
                        if not bayes_control_list:
                            st.warning(
                                "No control regions are selected, so Bayesian TBR cannot be run. "
                                "Choose another method or select at least one control region."
                            )
                            st.stop()
                    else:
                        # Data-Optimised / LASSO / Elastic Net methods: only use the
                        # model-selected base control regions. Do NOT fall back to the
                        # full candidate control pool if the model selected zero controls —
                        # that would silently change what Bayesian TBR is actually testing.
                        bayes_control_list = res.get("selected_regions", []) if res else []
                        if not bayes_control_list:
                            st.warning(
                                "The selected method did not retain any controls, so Bayesian TBR cannot be run for this method. "
                                "Choose another method, adjust exclusions, increase the control pool, or disable overly "
                                "restrictive validation settings."
                            )
                            st.stop()

                    bayes_base_control_list = list(bayes_control_list)
                    # Bayesian TBR always uses the same frequency and lag setup as the selected
                    # validation method (from validation_results), not an independently chosen one —
                    # this keeps the lag length (1-week vs 7-day) consistent with how the underlying
                    # validation run was configured.
                    bayes_include_lag = vres.get("include_lagged_controls", False)
                    bayes_lag_periods = bayes_freq_config["lag_periods"]
                    # Bayesian TBR always uses every base control (with coefficient shrinkage via
                    # priors, not hard LASSO/Elastic-Net selection), so the expected feature set is
                    # simply the base controls plus their lagged terms when lagging is enabled —
                    # not the upstream validation method's own selected_features.
                    bayes_feature_preview = (
                        bayes_base_control_list
                        + [f"{c}_lag{bayes_lag_periods}" for c in bayes_base_control_list]
                        if bayes_include_lag
                        else list(bayes_base_control_list)
                    )

                    st.caption(
                        f"⏱️ {bayes_freq_config['lag_label']} lagged controls: {'**enabled**' if bayes_include_lag else '**disabled**'} (using the {bayes_time_series_frequency} frequency and lag setup from the Measure Test Impact validation run)"
                    )
                    with st.expander("Controls used by Bayesian TBR", expanded=False):
                        st.write(f"**Base control regions ({len(bayes_base_control_list)}):**")
                        st.write(
                            ", ".join(bayes_base_control_list)
                            if bayes_base_control_list
                            else "_None_"
                        )
                        if bayes_include_lag:
                            st.write(f"**Number of model features:** {len(bayes_feature_preview)}")
                            st.write("**Model feature terms (including lagged terms):**")
                            st.write(
                                ", ".join(bayes_feature_preview)
                                if bayes_feature_preview
                                else "_None_"
                            )

                    # ---- Structural prior settings ----
                    use_structural_priors = st.checkbox(
                        "Use structurally informed coefficient priors",
                        value=False,
                        key="use_structural_priors",
                        help=(
                            "Controls how the Bayesian model's coefficient priors are set.\n\n"
                            "OFF (default): every control gets a fixed prior of Normal(0, σ=0.50). "
                            "All controls are treated equally.\n\n"
                            "ON: each control is scored by its structural distance to the "
                            "population-weighted test-group profile, using the same features and "
                            "weights as GeoMatch matching. Sigma bounds are then derived from the "
                            "median pre-period correlation between controls and the test KPI, so "
                            "the scale reflects how predictive your controls actually are.\n\n"
                            "Better structural match → wider sigma (more flexibility).\n"
                            "Weaker structural match → narrower sigma (shrunk toward zero).\n\n"
                            "The prior mean stays zero regardless. Only the width changes."
                        ),
                    )

                    use_ar1_errors = st.checkbox(
                        "Allow for noise streaks — AR(1) errors (recommended)",
                        value=True,
                        key="use_ar1_errors",
                        help=(
                            "KPI noise is often 'streaky': a high week tends to be followed by another high week, "
                            "and a low week by another low one.\n\n"
                            "ON (recommended): the model measures how streaky your data is and factors it in. "
                            "Streaky noise doesn't average out over the test window the way random ups and downs do, "
                            "so when streakiness is present the uncertainty range around the total uplift gets wider — "
                            "keeping the headline result honest.\n\n"
                            "OFF: each period's noise is treated as independent (the previous behaviour). "
                            "If your data isn't streaky, both settings give almost the same answer.\n\n"
                            "Technical note: residuals follow an AR(1) process — e(t) = \u03c1\u00b7e(t\u22121) + shock — with \u03c1 "
                            "estimated from the pre-period via the exact conditional likelihood. \u03c3 then acts as the "
                            "innovation SD (marginal residual SD = \u03c3 / sqrt(1 \u2212 \u03c1\u00b2)), and the predictive bands are "
                            "simulated AR(1) residual paths anchored on the last pre-period residual. Positive "
                            "autocorrelation (Durbin-Watson below ~2 in the validation tabs) is the signal that this "
                            "setting matters."
                        ),
                    )

                    _bayes_freq_blocked = st.session_state.get("frequency_mismatch_blocked", False)
                    if _bayes_freq_blocked:
                        st.info(
                            "Bayesian TBR is disabled until the frequency mismatch warning above (in the validation setup) is acknowledged or resolved."
                        )
                    if st.button(
                        "Run Bayesian Time-Based Regression (TBR)",
                        width="stretch",
                        type="primary",
                        key="run_bayes_tab4",
                        disabled=_bayes_freq_blocked,
                    ):
                        with st.spinner(f"Running Bayesian TBR using {selected_bayes_method}..."):
                            _bayes_config = BayesianConfig(
                                method_name=selected_bayes_method,
                                control_list=tuple(bayes_control_list),
                                test_regions=tuple(test_regions_val),
                                geo_col=geo_col,
                                feature_cols=tuple(active_features),
                                weight_dict=st.session_state.get("current_weights", None),
                                population_col=POPULATION_COL,
                                time_series_frequency=bayes_time_series_frequency,
                                frequency_config=bayes_freq_config,
                                include_lagged_controls=bayes_include_lag,
                                lag_periods=bayes_lag_periods,
                                use_structural_priors=st.session_state.get(
                                    "use_structural_priors", False
                                ),
                                use_ar1_errors=st.session_state.get("use_ar1_errors", True),
                                pre_start=pre_start,
                                pre_end=pre_end,
                                test_start=test_start,
                                test_end=test_end,
                                use_post=use_post,
                                post_start=post_start,
                                post_end=post_end,
                                # Sampling profile is session-configurable so tests and
                                # power users can use a reduced profile; production
                                # defaults are preserved.
                                mcmc_draws=int(st.session_state.get("bayes_mcmc_draws", 2000)),
                                mcmc_tune=int(st.session_state.get("bayes_mcmc_tune", 1000)),
                                mcmc_chains=int(st.session_state.get("bayes_mcmc_chains", 4)),
                                mcmc_target_accept=float(
                                    st.session_state.get("bayes_mcmc_target_accept", 0.95)
                                ),
                                mcmc_random_seed=int(
                                    st.session_state.get("bayes_mcmc_random_seed", 42)
                                ),
                            )
                            _bayes_result = run_bayesian(
                                model_agg_df=agg_df_bayes,
                                structural_agg_df=agg_df,
                                config=_bayes_config,
                                selected_metric=selected_metric,
                            )
                            # Structured messages from the pure service.
                            for _msg in _bayes_result.errors:
                                st.error(_msg)
                            for _msg in _bayes_result.warnings:
                                st.warning(_msg)
                            for _msg in _bayes_result.blockers:
                                st.error(_msg)
                            if _bayes_result.blockers:
                                st.stop()
                            if _bayes_result.completed:
                                # Serialisable summary for the UI; the PyMC trace is
                                # kept separately so result-only reruns never re-sample.
                                st.session_state.bayesian_results = _bayes_result.to_dict()
                                st.session_state.bayesian_trace = _bayes_result.trace
                                st.session_state.bayesian_interpretation_visible = True
                                # ---- Experiment record: stamp observed_impact (Stage 4). ----
                                st.session_state.experiment_bayesian_inputs = {
                                    "selected_bayes_method": selected_bayes_method,
                                    "use_structural_priors": st.session_state.get(
                                        "use_structural_priors", False
                                    ),
                                    "use_ar1_errors": st.session_state.get("use_ar1_errors", True),
                                    "bayes_control_list": sorted(
                                        str(c) for c in bayes_control_list
                                    ),
                                }
                                _stamp_bayesian_stage()

        # ---- Bayesian results display — IDENTICAL to working file ----
        if st.session_state.bayesian_results is not None:
            bayes = st.session_state.bayesian_results

            # Row 1: Pre-period fit metrics
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Pre-Period Correlation",
                f"{bayes['corr']:.3f}",
                help="How closely the Bayesian counterfactual fits the actual pre-period KPI.",
            )
            col2.metric(
                "Pre-Period R²",
                f"{bayes['r2']:.3f}",
                help="Proportion of variation in the test KPI explained by the controls (pre-period).",
            )
            col3.metric(
                "Pre-Period sMAPE",
                f"{bayes['smape']:.1f}%",
                help="Average percentage error of the Bayesian model in the pre-period.",
            )

            # Row 2: Uplift results
            uplift_label = f"{bayes['mean_uplift']:.0f}"
            if not np.isnan(bayes["uplift_pct"]):
                uplift_label += f"  ({bayes['uplift_pct']:.1f}%)"
            col5, col6, col7 = st.columns(3)
            col5.metric(
                "Estimated Incremental Uplift",
                uplift_label,
                help="Posterior mean incremental uplift during the test period, with percentage of predicted baseline.",
            )
            col6.metric(
                "P(Uplift > 0)",
                f"{bayes['prob_pos']:.1%}",
                help="Probability that the intervention had a positive impact.",
            )
            col7.metric(
                "94% Predictive Interval for Uplift",
                format_range(bayes["uplift_pi_lower"], bayes["uplift_pi_upper"], decimals=0),
                help="The interval within which the true uplift is expected to lie with 94% probability, including observation-level noise in the counterfactual. This is the primary readout for total impact.",
            )

            # ---- Line chart ----
            # Pre-period: 94% HDI / credible interval around the fitted counterfactual mean (no observation noise).
            # Test/post period: 94% posterior predictive interval (includes observation-level noise) — the
            # plausible range of actual counterfactual observations under the no-test scenario.
            all_dates_b = list(bayes["pre_dates"]) + list(bayes["test_dates"])
            all_actual_b = list(bayes["y_pre"]) + list(bayes["y_test_actual"])
            all_pred_b = list(bayes["y_pred_pre_mean"]) + list(bayes["y_pred_test_mean"])
            n_pre_pts = len(bayes["pre_dates"])
            n_test_pts = len(bayes["test_dates"])

            # Fitted-mean HDI band — populated for pre-period rows only, NaN elsewhere.
            all_mean_hdi_lower_b = list(bayes["pre_lower_mean_hdi"]) + [np.nan] * n_test_pts
            all_mean_hdi_upper_b = list(bayes["pre_upper_mean_hdi"]) + [np.nan] * n_test_pts
            # Predictive interval band — populated for test-period rows only, NaN elsewhere.
            all_pi_lower_b = [np.nan] * n_pre_pts + list(bayes["test_lower_pi"])
            all_pi_upper_b = [np.nan] * n_pre_pts + list(bayes["test_upper_pi"])
            interval_type_b = ["94% fitted mean interval (pre-period)"] * n_pre_pts + [
                "94% predictive interval (test/post)"
            ] * n_test_pts

            if bayes["post_dates"] is not None:
                n_post_pts = len(bayes["post_dates"])
                all_dates_b += list(bayes["post_dates"])
                all_actual_b += list(bayes["y_post_actual"])
                all_pred_b += list(bayes["y_pred_post_mean"])
                all_mean_hdi_lower_b += [np.nan] * n_post_pts
                all_mean_hdi_upper_b += [np.nan] * n_post_pts
                all_pi_lower_b += list(bayes["post_lower_pi"])
                all_pi_upper_b += list(bayes["post_upper_pi"])
                interval_type_b += ["94% predictive interval (test/post)"] * n_post_pts

            plot_df = pd.DataFrame(
                {
                    "Date": all_dates_b,
                    "Actual": all_actual_b,
                    "Counterfactual (mean)": all_pred_b,
                    "Lower 94% Fitted Mean Interval": all_mean_hdi_lower_b,
                    "Upper 94% Fitted Mean Interval": all_mean_hdi_upper_b,
                    "Lower 94% Predictive Interval": all_pi_lower_b,
                    "Upper 94% Predictive Interval": all_pi_upper_b,
                    "Interval Type": interval_type_b,
                }
            )

            _interval_cols_export = [
                "Actual",
                "Counterfactual (mean)",
                "Lower 94% Fitted Mean Interval",
                "Upper 94% Fitted Mean Interval",
                "Lower 94% Predictive Interval",
                "Upper 94% Predictive Interval",
            ]
            # ---- Export copies, captured here (before the toggle below mutates plot_df
            # in place) so the xlsx download always includes both an "Actual" sheet and
            # an "Indexed" sheet regardless of which plot_type is currently toggled. ----
            _actual_export_df_b = plot_df.copy()
            _pre_mean_export_b = np.mean(bayes["y_pre"])
            if _pre_mean_export_b > 0:
                _indexed_export_df_b = plot_df.copy()
                for _col in _interval_cols_export:
                    _indexed_export_df_b[_col] = (
                        _indexed_export_df_b[_col] / _pre_mean_export_b * 100
                    )
            else:
                _indexed_export_df_b = None

            bayes_plot_type = st.radio(
                "Display plot:",
                ["Actual", "Indexed (pre‑period avg = 100)"],
                horizontal=True,
                key="bayes_plot_toggle",
            )

            interval_cols = [
                "Actual",
                "Counterfactual (mean)",
                "Lower 94% Fitted Mean Interval",
                "Upper 94% Fitted Mean Interval",
                "Lower 94% Predictive Interval",
                "Upper 94% Predictive Interval",
            ]

            if bayes_plot_type == "Indexed (pre‑period avg = 100)":
                pre_mean_b = np.mean(bayes["y_pre"])
                if pre_mean_b > 0:
                    for col in interval_cols:
                        plot_df[col] = plot_df[col] / pre_mean_b * 100
                    y_label = f"{bayes['selected_metric']} (Indexed)"
                    title_suffix = "Indexed"
                else:
                    y_label = bayes["selected_metric"]
                    title_suffix = "Actual"
            else:
                y_label = bayes["selected_metric"]
                title_suffix = "Actual"

            fig_line = px.line(
                plot_df,
                x="Date",
                y=["Actual", "Counterfactual (mean)"],
                labels={"value": y_label, "Date": "Date"},
                title=f"Bayesian TBR: {title_suffix}",
            )
            # Pre-period 94% fitted mean interval band
            fig_line.add_scatter(
                x=plot_df["Date"],
                y=plot_df["Upper 94% Fitted Mean Interval"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                connectgaps=False,
            )
            fig_line.add_scatter(
                x=plot_df["Date"],
                y=plot_df["Lower 94% Fitted Mean Interval"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(0,100,200,0.15)",
                showlegend=True,
                name="94% fitted mean interval (pre-period)",
                connectgaps=False,
            )
            # Test/post-period 94% predictive interval band
            fig_line.add_scatter(
                x=plot_df["Date"],
                y=plot_df["Upper 94% Predictive Interval"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                connectgaps=False,
            )
            fig_line.add_scatter(
                x=plot_df["Date"],
                y=plot_df["Lower 94% Predictive Interval"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(0,150,80,0.2)",
                showlegend=True,
                name="94% predictive interval (test/post)",
                connectgaps=False,
            )
            if bayes["test_start_ts"] is not None:
                fig_line.add_vline(
                    x=bayes["test_start_ts"],
                    line_dash="dash",
                    line_color="red",
                    annotation_text="Test start",
                    annotation_position="top left",
                )
            if bayes["test_end_ts"] is not None:
                fig_line.add_vline(
                    x=bayes["test_end_ts"],
                    line_dash="dash",
                    line_color="orange",
                    annotation_text="Test end",
                    annotation_position="top right",
                )
            fig_line.update_layout(yaxis_title=y_label)
            st.plotly_chart(fig_line, width="stretch")
            st.download_button(
                "⬇️ Download chart data (.xlsx)",
                data=build_chart_data_xlsx(
                    {
                        "Actual": _actual_export_df_b,
                        "Indexed (pre-period avg=100)": _indexed_export_df_b,
                    }
                ),
                file_name="bayesian_tbr_chart_data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_bayes_chart_data",
            )
            _ar1_caption = ""
            if bayes.get("use_ar1_errors") and bayes.get("rho_mean") is not None:
                _ar1_caption = (
                    f" The model also measured how streaky the noise is (\u2248 {bayes['rho_mean']:.2f} on a scale "
                    "where 0 = no streaks and 1 = very streaky) and has factored this into the green band and the "
                    "uplift range — streaky noise makes totals more uncertain, so the ranges widen accordingly. "
                    f"(Technical: AR(1) residual model; 94% interval for \u03c1: {bayes['rho_hdi_lower']:.2f} to "
                    f"{bayes['rho_hdi_upper']:.2f}.)"
                )
            st.caption(
                "**Blue** (pre-period) = uncertainty in the average fitted relationship, no noise added. "
                "**Green** (test/post) = the plausible range of actual outcomes if there had been no test, "
                f"including normal period-to-period ({bayes.get('frequency_config', {}).get('period_label_singular', 'week')}-to-{bayes.get('frequency_config', {}).get('period_label_singular', 'week')}) noise. "
                "Compare actuals to the counterfactual line and green band "
                "to judge the test period — the uplift cards above are the main readout for total impact."
                + _ar1_caption
            )

            # ---- Posterior uplift distribution histogram ----
            fig_b = px.histogram(
                pd.DataFrame({"uplift": bayes["uplift_samples"]}),
                x="uplift",
                nbins=50,
                title="Posterior Uplift Distribution",
            )
            fig_b.update_yaxes(title_text="Frequency")
            fig_b.update_xaxes(title_text="Incremental Uplift")
            fig_b.add_vline(x=0, line_dash="dash", line_color="red")
            fig_b.add_vline(
                x=bayes["uplift_pi_lower"],
                line_dash="dot",
                line_color="green",
                annotation_text="94% lower (predictive)",
                annotation_position="top",
            )
            fig_b.add_vline(
                x=bayes["uplift_pi_upper"],
                line_dash="dot",
                line_color="green",
                annotation_text="94% upper (predictive)",
                annotation_position="top",
            )
            fig_b.add_vline(
                x=bayes["mean_uplift"],
                line_dash="solid",
                line_color="blue",
                annotation_text=f"Mean = {bayes['mean_uplift']:.0f}",
                annotation_position="top",
            )
            st.plotly_chart(fig_b, width="stretch")
            st.download_button(
                "⬇️ Download chart data (.xlsx)",
                data=build_chart_data_xlsx(
                    {
                        "Posterior Uplift Distribution": pd.DataFrame(
                            {"Uplift": bayes["uplift_samples"]}
                        ),
                    }
                ),
                file_name="posterior_uplift_distribution_data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_posterior_uplift_data",
            )
            st.caption(
                "The histogram shows the distribution of possible uplift values, drawn from the posterior predictive counterfactual totals. The blue line marks the mean estimate, red is zero (no effect), and the green dashed lines show the 94% predictive interval."
            )

            _bayes_lag_drop_meta = bayes.get("lag_drop_metadata")
            if (
                bayes.get("include_lagged_controls")
                and bayes.get("time_series_frequency") == "daily"
                and _bayes_lag_drop_meta
            ):
                if _bayes_lag_drop_meta.get("lag_drop_pct", 0) > 20:
                    st.warning(
                        f"⚠️ Daily 7-day lagged controls require matching dates exactly 7 calendar days earlier. "
                        f"{_bayes_lag_drop_meta['rows_dropped_due_to_lag']} of {_bayes_lag_drop_meta['rows_before_lag_drop']} rows "
                        f"({_bayes_lag_drop_meta['lag_drop_pct']:.1f}%) were dropped because those lag dates were missing. "
                        f"Check whether your daily data has gaps."
                    )

            # ---- Coefficient priors used ----
            with st.expander("Coefficient priors used in Bayesian TBR", expanded=False):
                _bayes_lag_label = bayes.get("lag_label", "1-week")
                st.write(f"**Prior style:** {bayes['prior_style']}")
                st.write(
                    f"**{_bayes_lag_label} lagged controls:** {'Enabled' if bayes.get('include_lagged_controls') else 'Disabled'}"
                )
                st.write(
                    f"**Base control regions:** {', '.join(bayes.get('base_control_list', bayes.get('control_list', []))) or '_None_'}"
                )
                st.write(
                    f"**Number of model features:** {len(bayes.get('model_feature_cols', bayes.get('control_list', [])))}"
                )
                if bayes.get("include_lagged_controls"):
                    st.write(
                        f"**Model features used:** {', '.join(bayes.get('model_feature_cols', []))}"
                    )
                if bayes["prior_style"] == "Structurally informed":
                    st.caption(
                        f"**Sigma bounds (data-driven):** "
                        f"min = {bayes['min_prior_sigma']:.3f}, "
                        f"max = {bayes['max_prior_sigma']:.3f}. "
                        f"Bounds are derived from the median absolute pre-period correlation between "
                        f"control and test KPIs — higher tracking quality raises the ceiling."
                    )
                st.dataframe(bayes["structural_prior_df"], width="stretch")
                st.caption(
                    "The prior mean remains zero for every control. Structural similarity only changes the prior width: "
                    "better structural matches are allowed more coefficient flexibility, while weaker structural matches "
                    f"are shrunk more strongly toward zero. If {_bayes_lag_label} lagged controls are enabled, each region's lagged "
                    "term uses the same structural prior sigma as its same-period term."
                )

            # ---- MCMC Diagnostics (guarded: requires the posterior trace) ----
            _trace = st.session_state.get("bayesian_trace")
            if _trace is None:
                st.caption(
                    "MCMC diagnostics are not available because the posterior trace is no "
                    "longer in memory. Re-run the Bayesian model to regenerate them."
                )
            else:
                _render_mcmc_diagnostics(bayes, _trace)

        # ---- Bayesian interpretation ----
        if st.session_state.get("bayesian_interpretation_visible", False):
            with st.expander("How to interpret Bayesian TBR results", expanded=False):
                st.markdown("""
                **Bayesian TBR – Assessing Test Impact**

                Focus on these three measures:

                **Estimated Incremental Uplift** (posterior mean)
                - The model's best estimate of the intervention's impact.
                - Positive values suggest the test increased the KPI.

                **94% Predictive Interval**
                - The interval within which the future uplift is expected to lie with 94% probability.
                - If entirely above zero, there is strong evidence of a positive effect.
                - If it crosses zero, the result is uncertain.

                **P(Uplift > 0)**
                - The probability that the intervention had a positive impact.
                - High values (e.g., >0.95) indicate strong confidence.

                **Rule of thumb**
                - Positive uplift + interval above zero + high probability = strong evidence.

                **Reading the chart**
                - The blue band (pre-period) is the 94% HDI / credible interval around the *fitted counterfactual mean* — it does not include observation-level noise, so it is narrower.
                - The green band (test/post-period) is the 94% posterior predictive interval — the plausible range of *actual counterfactual observations* under the no-test scenario, including observation-level noise. This is what you should compare the actuals against.
                - When "Allow for noise streaks" is on (the default), the model checks whether noise runs in streaks — a high period followed by another high period. If it does, the green band and the uplift range are widened to match, because streaky noise doesn't cancel out over the test window the way independent noise would. (Technically: an AR(1) error model — e(t) = \u03c1\u00b7e(t\u22121) + noise — fitted via the exact conditional likelihood; the bands are simulated AR(1) residual paths anchored on the last pre-period residual, so multi-period totals inherit the autocorrelation.)
                """)


with tab3:
    render_power_test_sizing_tab(
        experiment_record_factory=_experiment_record,
        save_experiment_record=_save_experiment_record,
    )

with tab4:
    render_media_delivery_tab()

with tab5:
    render_effect_plausibility_tab()

with tab6:
    render_design_recommendation_tab()


# ------------------------------------------------------------
# Experiment record (Stage 4) — reconcile and display
# ------------------------------------------------------------
_reconcile_experiment_record()
_lifecycle_status_slot.empty()
with _lifecycle_status_slot.container():
    render_lifecycle_status_summary()
render_experiment_record()

# ------------------------------------------------------------
# Sidebar data quality footer
# ------------------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown("### 5. Data Quality Check")
st.sidebar.caption(f"**{market}** - **{geography_level}**")
if validation_issues:
    for issue in validation_issues[:5]:
        st.sidebar.caption(issue)
    if recommendations:
        with st.sidebar.expander("💡 Recommendations", expanded=False):
            for rec in recommendations[:5]:
                st.caption(rec)
    st.sidebar.metric(
        "Data Quality", issue_severity, help=f"Found {len(validation_issues)} potential issues"
    )
else:
    st.sidebar.success(f"✅ Data quality check passed for {market} ({geography_level})")
