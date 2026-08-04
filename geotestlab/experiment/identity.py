"""Experiment identity: stable identifier and UTC timestamps."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def utc_now_iso(now=None) -> str:
    """Current UTC time as a sortable ISO-8601 string (deterministic when ``now`` given)."""
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_experiment_id(now=None) -> str:
    """Generate a stable, human-friendly experiment identifier.

    Format ``EXP-YYYYMMDD-XXXX`` (XXXX is a 4-char random token). Deterministic
    when ``now`` is supplied (token still random, matching production behaviour).
    """
    day = utc_now_iso(now)[:10].replace("-", "")
    token = secrets.token_hex(2).upper()
    return f"EXP-{day}-{token}"
