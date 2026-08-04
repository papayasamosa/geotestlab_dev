"""Content-level SHA-256 identities (Stage 2).

The validation identity previously used file name and byte length. This module
adds SHA-256 digests over the actual content:

- uploaded source bytes;
- normalised analytical data (long-format KPI frame);
- bundled geography workbook bytes;
- selected market sheet;
- candidate-region universe.

Only digests are ever stored/exported — raw sensitive values are never included
in exported metadata.
"""

from __future__ import annotations

import hashlib

import pandas as pd

from geotestlab.experiment.fingerprints import canonical_json

_SHA256_PREFIX = "sha256:"


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes (prefixed)."""
    return f"{_SHA256_PREFIX}{hashlib.sha256(bytes(data)).hexdigest()}"


def sha256_content(obj) -> str:
    """SHA-256 over the canonical JSON of any value (value-tolerant)."""
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def canonical_frame(df) -> pd.DataFrame | None:
    """Row-order-independent canonical form of a frame (sorted by all columns).

    ``None`` in, ``None`` out. Sorting uses a stable key built from the
    stringified rows so mixed-type columns (dates, numbers, None) sort safely.
    """
    if df is None:
        return None
    frame = df.copy()
    sort_key = frame.astype(str).agg("|".join, axis=1)
    frame = frame.loc[sort_key.sort_values(kind="mergesort").index].reset_index(drop=True)
    return frame


def analytical_data_digest(df) -> str | None:
    """SHA-256 identity of the normalised analytical (long) KPI data."""
    if df is None:
        return None
    return sha256_content(canonical_frame(df).to_dict(orient="records"))


def market_sheet_digest(sheet_df) -> str | None:
    """SHA-256 identity of the selected market sheet."""
    if sheet_df is None:
        return None
    return sha256_content(canonical_frame(sheet_df).to_dict(orient="records"))


def candidate_universe_digest(regions) -> str | None:
    """SHA-256 identity of the candidate-region universe (sorted, deduped)."""
    if regions is None:
        return None
    return sha256_content(sorted({str(r) for r in regions}))


def build_content_digests(
    source_bytes=None,
    analytical_data=None,
    workbook_bytes=None,
    market_sheet=None,
    candidate_universe=None,
) -> dict:
    """JSON-safe dict of content digests (raw content is never included).

    Each digest is optional and reported as ``None`` when the source content is
    not available. Keys: ``source_bytes``, ``analytical_data``,
    ``geography_workbook``, ``market_sheet``, ``candidate_universe``.
    """
    return {
        "source_bytes": sha256_bytes(source_bytes) if source_bytes is not None else None,
        "analytical_data": analytical_data_digest(analytical_data),
        "geography_workbook": sha256_bytes(workbook_bytes) if workbook_bytes is not None else None,
        "market_sheet": market_sheet_digest(market_sheet),
        "candidate_universe": candidate_universe_digest(candidate_universe),
    }
