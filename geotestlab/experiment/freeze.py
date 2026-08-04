"""Frozen approved design versions and planned-versus-analysed comparison.

Frozen versions are IMMUTABLE: data is deep-copied on store, on return, and on
export, so a caller cannot mutate approved history through the original input,
the ``freeze_design`` return value, ``active_frozen_version``, or an export
dict. A frozen version captures the complete design snapshot (not just a
fingerprint and period dictionary).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from geotestlab.experiment.identity import utc_now_iso
from geotestlab.experiment.records import ExperimentRecord, add_note

FROZEN_SCHEMA_VERSION = "frozen-design/v1"


@dataclass
class FrozenVersion:
    """One immutable approved design version (typed + schema-versioned)."""

    version: int
    frozen_at: str
    input_fingerprint: str
    planned: dict = field(default_factory=dict)
    # Complete design snapshot (regions, KPI/frequency, periods, weights,
    # validation settings, data-quality summary, source digests, versions, ...).
    design: dict = field(default_factory=dict)
    label: str = ""
    schema_version: str = FROZEN_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """JSON-safe dict; every nested container is deep-copied."""
        return {
            "version": int(self.version),
            "frozen_at": self.frozen_at,
            "input_fingerprint": self.input_fingerprint,
            "label": self.label,
            "planned": copy.deepcopy(dict(self.planned or {})),
            "design": copy.deepcopy(dict(self.design or {})),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrozenVersion:
        """Rebuild from a dict (tolerant of v1 plain frozen dicts without
        ``design`` / ``schema_version``)."""
        return cls(
            version=int(data.get("version", 1)),
            frozen_at=str(data.get("frozen_at", "")),
            input_fingerprint=str(data.get("input_fingerprint", "")),
            label=str(data.get("label", "")),
            planned=copy.deepcopy(dict(data.get("planned") or {})),
            design=copy.deepcopy(dict(data.get("design") or {})),
            schema_version=str(data.get("schema_version", FROZEN_SCHEMA_VERSION)),
        )


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
    design: dict | None = None,
    now=None,
) -> dict:
    """Freeze an approved design version onto the record (immutable).

    ``planned`` is the planned-period dict (pre/test/post boundaries plus the
    planned/analysed/excluded test-period counts). ``design`` is the optional
    complete design snapshot (regions, KPI/frequency, periods, weights,
    validation settings, data-quality summary, source-data digests, tool and
    methodology versions, analyst label/notes, approved power result when later
    available). Each freeze appends a new immutable version; the record keeps
    the full version history. The returned dict is an independent deep copy —
    mutating it never mutates the stored version.
    """
    version = len(record.frozen_versions) + 1
    frozen = FrozenVersion(
        version=version,
        frozen_at=utc_now_iso(now),
        input_fingerprint=current_fingerprint,
        label=label,
        planned=copy.deepcopy(dict(planned or {})),
        design=copy.deepcopy(dict(design or {})),
    )
    record.frozen_versions.append(frozen)
    add_note(
        record,
        f"Design frozen as version {version} (fingerprint {current_fingerprint}).",
        now,
    )
    return frozen.to_dict()


def is_frozen(record: ExperimentRecord) -> bool:
    return len(record.frozen_versions) > 0


def active_frozen_version(record: ExperimentRecord) -> dict | None:
    """The most recently frozen design version (independent deep copy), or None."""
    if not record.frozen_versions:
        return None
    return record.frozen_versions[-1].to_dict()


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
