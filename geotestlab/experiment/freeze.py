"""Frozen approved design versions and planned-versus-analysed comparison."""

from __future__ import annotations

from geotestlab.experiment.identity import utc_now_iso
from geotestlab.experiment.records import ExperimentRecord, add_note


def _planned_period_counts(planned: dict) -> dict:
    """Normalised period counts from a planned dict (tolerant of missing keys)."""
    planned_test = planned.get("planned_test_periods")
    analysed_test = planned.get("analysed_test_periods")
    excluded_test = planned.get("excluded_test_periods")
    if planned_test is None and analysed_test is not None and excluded_test is not None:
        planned_test = analysed_test + excluded_test
    return {
        "planned_test_periods": planned_test,
        "analysed_test_periods": analysed_test,
        "excluded_test_periods": excluded_test,
    }


def freeze_design(
    record: ExperimentRecord,
    planned: dict,
    current_fingerprint: str,
    label: str = "",
    now=None,
) -> dict:
    """Freeze an approved design version onto the record.

    ``planned`` is the planned-period dict (pre/test/post boundaries plus the
    planned/analysed/excluded test-period counts). Each freeze appends a new
    immutable version; the record keeps the full version history.
    """
    version = len(record.frozen_versions) + 1
    frozen = {
        "version": version,
        "frozen_at": utc_now_iso(now),
        "input_fingerprint": current_fingerprint,
        "label": label,
        "planned": dict(planned),
    }
    record.frozen_versions.append(frozen)
    add_note(
        record,
        f"Design frozen as version {version} (fingerprint {current_fingerprint}).",
        now,
    )
    return frozen


def is_frozen(record: ExperimentRecord) -> bool:
    return len(record.frozen_versions) > 0


def active_frozen_version(record: ExperimentRecord) -> dict | None:
    """The most recently frozen design version, or None."""
    if not record.frozen_versions:
        return None
    return record.frozen_versions[-1]


def planned_vs_analysed(record: ExperimentRecord) -> dict:
    """Compare the active frozen design's planned periods with the latest analysed.

    Returns a JSON-safe comparison dict with ``matches`` False when anything
    differs (including when there is no frozen version or no analysed summary).
    """
    frozen = active_frozen_version(record)
    analysed = record.analysed
    if frozen is None:
        return {
            "frozen": False,
            "matches": False,
            "differences": ["No frozen design version exists."],
            "planned": None,
            "analysed": None,
        }
    planned = dict(frozen.get("planned") or {})

    def _iso(v):
        if v is None:
            return None
        from pandas import Timestamp

        try:
            return Timestamp(v).isoformat()
        except Exception:
            return str(v)

    planned_periods = {
        "pre_start": _iso(planned.get("pre_start")),
        "pre_end": _iso(planned.get("pre_end")),
        "test_start": _iso(planned.get("test_start")),
        "test_end": _iso(planned.get("test_end")),
        "use_post": bool(planned.get("use_post", False)),
        "post_start": _iso(planned.get("post_start")),
        "post_end": _iso(planned.get("post_end")),
        "time_series_frequency": planned.get("time_series_frequency"),
    }
    if analysed is not None:
        analysed = dict(analysed)
    analysed_periods = {
        "pre_start": _iso(analysed.get("pre_start")) if analysed else None,
        "pre_end": _iso(analysed.get("pre_end")) if analysed else None,
        "test_start": _iso(analysed.get("test_start")) if analysed else None,
        "test_end": _iso(analysed.get("test_end")) if analysed else None,
        "use_post": bool(analysed.get("use_post", False)) if analysed else False,
        "post_start": _iso(analysed.get("post_start")) if analysed else None,
        "post_end": _iso(analysed.get("post_end")) if analysed else None,
        "time_series_frequency": (analysed or {}).get("time_series_frequency"),
    }

    differences = []
    for key in (
        "pre_start",
        "pre_end",
        "test_start",
        "test_end",
        "use_post",
        "post_start",
        "post_end",
        "time_series_frequency",
    ):
        pv = planned_periods[key]
        av = analysed_periods[key]
        if pv != av:
            differences.append(f"{key}: planned {pv!r} vs analysed {av!r}")

    planned_counts = _planned_period_counts(planned)
    analysed_counts = _planned_period_counts(analysed) if analysed else {}
    if planned_counts.get("planned_test_periods") != analysed_counts.get("planned_test_periods"):
        differences.append(
            "planned test period count: "
            f"planned {planned_counts.get('planned_test_periods')} vs "
            f"analysed {analysed_counts.get('planned_test_periods')}"
        )
    if planned_counts.get("analysed_test_periods") != analysed_counts.get("analysed_test_periods"):
        differences.append(
            "analysed test period count: "
            f"planned {planned_counts.get('analysed_test_periods')} vs "
            f"analysed {analysed_counts.get('analysed_test_periods')}"
        )

    return {
        "frozen": True,
        "matches": not differences,
        "differences": differences,
        "version": frozen.get("version"),
        "frozen_at": frozen.get("frozen_at"),
        "frozen_fingerprint": frozen.get("input_fingerprint"),
        "current_fingerprint": record.input_fingerprint,
        "design_changed_since_freeze": record.input_fingerprint != frozen.get("input_fingerprint"),
        "planned": planned_periods,
        "analysed": analysed_periods,
        "planned_counts": planned_counts,
        "analysed_counts": analysed_counts,
    }
