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

The frame canonical form is COLLISION-FREE: rows are sorted by a type-preserving
canonical key (JSON-encoded typed cells, never delimiter-joined strings), so
``("a|b", "c")`` and ``("a", "b|c")``, ``1`` and ``"1"``, ``None`` and
``"None"``, ``NaN`` and ``"nan"``, and timestamps and identical ISO strings can
never collide.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime

import numpy as np
import pandas as pd

from geotestlab.experiment.fingerprints import _coerce, canonical_json

_SHA256_PREFIX = "sha256:"


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes (prefixed)."""
    return f"{_SHA256_PREFIX}{hashlib.sha256(bytes(data)).hexdigest()}"


def sha256_content(obj) -> str:
    """SHA-256 over the canonical JSON of any value (value-tolerant)."""
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def _type_tag(value) -> str:
    """Stable type tag for a cell (used so timestamps never collide with the
    identical ISO string and typed values sort consistently)."""
    if value is None:
        return "none"
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return "datetime"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (bool, np.bool_)):
        return "bool"
    if isinstance(value, (int, np.integer)):
        return "int"
    if isinstance(value, (float, np.floating)):
        return "float"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (list, tuple, np.ndarray, pd.Series)):
        return "list"
    return "other"


def _canonical_cell(value) -> str:
    """Type-preserving canonical key for one cell.

    JSON-encodes ``[type_tag, coerced]`` so distinct typed values never collide
    (int ``1`` vs str ``"1"``, ``None`` vs ``"None"``, ``NaN`` vs ``"nan"``, and
    timestamps vs identical ISO strings all differ), and the encoded cell is
    self-delimiting (no ``|``-join collisions).
    """
    return json.dumps(
        [_type_tag(value), _coerce(value)],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _typed_records(df: pd.DataFrame) -> list:
    """Type-preserving records of a frame for content hashing.

    Every cell is encoded as ``[type_tag, coerced]`` so the digest path (which
    reuses the value-tolerant canonical JSON) never collapses distinct typed
    values: a timestamp and the identical ISO string produce different digests.
    """
    return [
        {str(col): [_type_tag(df.iloc[i][col]), _coerce(df.iloc[i][col])] for col in df.columns}
        for i in range(len(df))
    ]


def canonical_frame(df) -> pd.DataFrame | None:
    """Row- and column-order-independent canonical form of a frame.

    ``None`` in, ``None`` out. Rows are sorted by a type-preserving canonical
    row key (a tuple of JSON-encoded typed cells — never a delimiter-joined
    string, so ``("a|b", "c")`` and ``("a", "b|c")`` cannot collide), and
    columns are sorted by a stable type-safe key (column-order policy). Sorting
    uses a stable mergesort so duplicate rows keep a deterministic order.
    """
    if df is None:
        return None
    frame = df.copy()
    frame = frame[sorted(frame.columns, key=lambda c: (type(c).__name__, str(c)))]
    keys = frame.apply(lambda row: tuple(_canonical_cell(v) for v in row), axis=1)
    frame = frame.loc[keys.sort_values(kind="mergesort").index].reset_index(drop=True)
    return frame


def material_file_identity(path) -> dict | None:
    """Material identity of a file for cache invalidation.

    Returns ``{path, size, mtime_ns}`` (absolute path) or ``None`` when the
    file cannot be stat'ed. Identity changes when a file is replaced even with
    same-size content (``mtime_ns`` changes), so caches keyed on this identity
    are invalidated correctly.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return {
        "path": os.path.abspath(path),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def analytical_data_digest(df) -> str | None:
    """SHA-256 identity of the normalised analytical (long) KPI data."""
    if df is None:
        return None
    return sha256_content(_typed_records(canonical_frame(df)))


def market_sheet_digest(sheet_df) -> str | None:
    """SHA-256 identity of the selected market sheet."""
    if sheet_df is None:
        return None
    return sha256_content(_typed_records(canonical_frame(sheet_df)))


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
