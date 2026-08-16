"""Data-quality report rendering and the pre-run validation-issue scan.

Extracted from the ``geotestmatch.py`` monolith in PR9 (legacy UI deletion
and bootstrap cleanup) — these helpers only read/write ``st.session_state``
and their own parameters, with no dependency on the app's runtime
matching/validation module-level state, so they move here unchanged.
"""

from __future__ import annotations

import numpy as np
import streamlit as st
from scipy import stats

from geotestlab.data.mapping import uncovered_required_regions


def quality_blocking_errors() -> list[str]:
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
    with st.expander("Data Quality Report", expanded=has_blockers):
        if has_blockers:
            for err in report.blocking_errors:
                st.error(err)
        else:
            st.success(
                f"Parsed **{report.source_rows_read:,}** source row(s) into "
                f"**{report.observations_retained:,}** usable observation(s)."
            )

        for w in report.warnings:
            st.warning(w)

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
        st.warning(f"Unmapped regions: {shown}")
        if mapping_report.unmapped_rows is not None and len(mapping_report.unmapped_rows):
            st.download_button(
                "⬇️ Download unmapped rows (CSV)",
                data=mapping_report.unmapped_rows.to_csv(index=False).encode("utf-8"),
                file_name="kpi_unmapped_rows.csv",
                mime="text/csv",
                key="kpi_unmapped_rows_download",
            )


def validate_data(
    df, required_cols, geo_col=None, *, missing_threshold: float, outlier_std_threshold: float
):
    """Scan a matching dataset for issues and return (issues, recommendations).

    ``missing_threshold``/``outlier_std_threshold`` are supplied by the caller
    (the app's ``CONFIG``) so this module stays free of app-level config.
    """
    issues = []
    recommendations = []
    if len(df) == 0:
        issues.append("No data available for the selected filters")
        recommendations.append("Try a different market or geography grouping")
        return issues, recommendations
    if not required_cols:
        issues.append("No numeric matching features detected")
        recommendations.append("Check that demographic columns are numeric")
        return issues, recommendations
    missing_pct = df[required_cols].isnull().mean() * 100
    high_missing = missing_pct[missing_pct > missing_threshold]
    if len(high_missing) > 0:
        issues.append(f"High missing values (> {missing_threshold}%): {dict(high_missing)}")
        recommendations.append(
            f"Consider removing from matching: {', '.join(high_missing.index[:3])}"
        )
    constant_cols = []
    for col in required_cols:
        if df[col].nunique(dropna=False) <= 1:
            constant_cols.append(col)
    if constant_cols:
        issues.append(f"Constant features detected: {constant_cols[:5]}")
        recommendations.append(
            f"Remove these features because they do not help matching: {', '.join(constant_cols[:3])}"
        )
    outlier_dict = {}
    for col in required_cols:
        if df[col].count() > 10:
            clean_data = df[col].dropna()
            if len(clean_data) > 0 and clean_data.std() > 0:
                z_scores = np.abs(stats.zscore(clean_data))
                outlier_mask = z_scores > outlier_std_threshold
                if outlier_mask.any():
                    outlier_indices = clean_data.index[outlier_mask]
                    if geo_col and len(outlier_indices) > 0:
                        outlier_regions = df.loc[outlier_indices, geo_col].tolist()
                    else:
                        outlier_regions = ["Unknown"]
                    outlier_dict[col] = outlier_regions[:3]
    if outlier_dict:
        issues.append(f"Extreme outliers detected (> {outlier_std_threshold} std dev)")
        for col, regions in list(outlier_dict.items())[:3]:
            issues.append(f"   • {col}: {', '.join(str(r) for r in regions)}")
        recommendations.append(
            "Investigate outlier regions for data errors or consider excluding them"
        )
    if len(df) < 3:
        issues.append(f"Very small sample size: {len(df)} geographies")
        recommendations.append("Try a more granular geography grouping, if available")
    return issues, recommendations
