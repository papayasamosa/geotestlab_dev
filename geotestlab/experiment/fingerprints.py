"""Deterministic input fingerprints.

A fingerprint is a SHA-256 hex digest over a canonical JSON serialisation of the
workflow inputs (sorted keys, stable separators, tolerant value coercion), so
the same inputs always produce the same fingerprint regardless of dict ordering
or numpy/pandas value types.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime

import numpy as np
import pandas as pd

_FINGERPRINT_PREFIX = "fp1:"


def _coerce(value):
    """Coerce a value to a JSON-serialisable, deterministic form."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _coerce(float(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return _coerce(value.to_pydatetime())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (np.ndarray,)):
        return [_coerce(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (pd.Series,)):
        return _coerce(value.tolist())
    if isinstance(value, pd.DataFrame):
        return _coerce(value.to_dict(orient="records"))
    try:
        return str(value)
    except Exception:
        return repr(value)


def canonical_json(inputs) -> str:
    """Deterministic JSON serialisation of the inputs (sorted keys, compact)."""
    return json.dumps(
        _coerce(inputs),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def compute_input_fingerprint(inputs) -> str:
    """SHA-256 hex digest of the canonical JSON of ``inputs`` (prefixed)."""
    digest = hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest()
    return f"{_FINGERPRINT_PREFIX}{digest}"
