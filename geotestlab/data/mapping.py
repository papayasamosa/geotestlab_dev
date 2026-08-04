"""Region mapping for uploaded KPI data: raw labels -> canonical geographies.

Streamlit-free. The application computes the mapping report *before* a run —
as soon as the uploaded file, market, geography level, mapping source and
selected metric are known — so that mapped and unmapped geographies are
reported, and modelling is blocked when a required selected test region has
no mapped data, without requiring a prior run.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from geotestlab.data.models import RegionMappingReport, compute_mapping_report


def build_region_mapping(df_long, valid_regions, adobe_to_geo):
    """Map each raw region label to a canonical geography.

    ``df_long`` must contain a ``region_raw`` column. Each raw label is
    resolved through ``adobe_to_geo`` (raw -> canonical) first, falling back
    to a direct match against ``valid_regions`` (the full candidate geography
    universe, not just the already-selected regions). Labels that resolve
    through neither become ``None`` (unmapped).

    Adds ``region_clean``, ``mapped_geo`` and ``region`` columns to the input
    frame, so callers should pass a copy they are happy to mutate.
    """
    all_geomatch_regions = set(valid_regions)
    df_long["region_clean"] = df_long["region_raw"].astype(str).str.strip()
    df_long["mapped_geo"] = df_long["region_clean"].map(adobe_to_geo)

    def final_region_name(row):
        if pd.notna(row["mapped_geo"]):
            return row["mapped_geo"]
        elif row["region_clean"] in all_geomatch_regions:
            return row["region_clean"]
        else:
            return None

    df_long["region"] = df_long.apply(final_region_name, axis=1)
    return df_long


def compute_region_mapping_report(
    df_long, valid_regions, adobe_to_geo, metric_name=None
) -> RegionMappingReport:
    """Build a :class:`RegionMappingReport` for the uploaded long-format data.

    When ``metric_name`` is provided, only that metric's rows are mapped — the
    same filtering the modelling run applies — so the report reflects the data
    that would actually be analysed. The caller's ``df_long`` is never mutated.
    """
    if metric_name is not None:
        df_work = df_long[df_long["metric_name"] == metric_name].copy()
    else:
        df_work = df_long.copy()
    mapped = build_region_mapping(df_work, valid_regions, adobe_to_geo)
    return compute_mapping_report(mapped)


def uncovered_required_regions(
    mapping_report: RegionMappingReport, required_regions
) -> tuple[str, ...]:
    """Required regions with no mapped data in the KPI file.

    A required region is treated as unmapped (and therefore a blocker) when
    the mapped data does not cover it — either it is absent from the file or
    its raw label could not be resolved. Unused raw regions that fail to map
    are not returned.
    """
    covered = set(mapping_report.covered_regions)
    return tuple(r for r in required_regions if r not in covered)


def _iso_day(value) -> str:
    """Normalise a date-like value to a deterministic ISO-8601 string.

    Midnight timestamps (the common case for date-only pickers) collapse to
    ``YYYY-MM-DD``; timestamps with a real time component keep it.
    """
    try:
        from pandas import Timestamp

        ts = Timestamp(value)
        iso = ts.isoformat()
        if ts == ts.normalize():
            return iso[:10]
        return iso
    except Exception:
        return str(value)


def region_mapping_fingerprint(
    *,
    file_name: str | None,
    file_size: int | None,
    market: str,
    geo_col: str,
    selected_metric: str,
    agg_col: str | None,
    mapping_source: str,
    file_sha256: str | None = None,
    kpi_pattern_source_digest: str | None = None,
    candidate_universe_digest: str | None = None,
    kpi_pattern_date_range=None,
    mapping_reference_digest: str | None = None,
) -> dict[str, Any]:
    """Deterministic identity of the mapping-report inputs.

    The mapping report is reused across reruns while this fingerprint is
    unchanged, so display-only interactions never recompute it. Any material
    change — file (name, size, or content SHA-256), KPI Pattern source digest,
    market, geography level, selected metric, selected KPI Pattern date range,
    aggregation column, candidate universe, mapping reference, or mapping
    source — changes the fingerprint and invalidates the stored report.

    The ``*_digest`` inputs are precomputed SHA-256 identities (digests only,
    never raw content) supplied by the caller.
    """
    _range = None
    if kpi_pattern_date_range:
        try:
            _range = tuple(sorted(_iso_day(d) for d in kpi_pattern_date_range))
        except Exception:
            _range = tuple(str(d) for d in kpi_pattern_date_range)
    return {
        "file_name": file_name,
        "file_size": file_size,
        "file_sha256": file_sha256,
        "market": market,
        "geo_col": geo_col,
        "selected_metric": selected_metric,
        "agg_col": agg_col,
        "mapping_source": mapping_source,
        "kpi_pattern_source_digest": kpi_pattern_source_digest,
        "candidate_universe_digest": candidate_universe_digest,
        "kpi_pattern_date_range": _range,
        "mapping_reference_digest": mapping_reference_digest,
    }
