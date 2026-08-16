"""Reusable status-line rendering, so status is never colour-only.

See the UX overhaul programme, section 11 (accessibility acceptance
criteria: "status must not rely on colour alone").
"""

from __future__ import annotations

from enum import Enum
from typing import Final

import streamlit as st


class StatusTone(Enum):
    """The small, fixed set of status tones used across analytical pages."""

    GOOD = "good"
    WARNING = "warning"
    BAD = "bad"
    NEUTRAL = "neutral"


_TONE_ICONS: Final[dict[StatusTone, str]] = {
    StatusTone.GOOD: "✅",
    StatusTone.WARNING: "⚠️",
    StatusTone.BAD: "🛑",
    StatusTone.NEUTRAL: "•",
}


def render_status_line(
    label: str,
    status_text: str,
    tone: StatusTone = StatusTone.NEUTRAL,
    *,
    detail: str | None = None,
) -> None:
    """Render one ``label: status`` line with an icon carrying the tone.

    The icon (not colour) is the primary signal, so the line remains legible
    to a colour-blind analyst or under a forced high-contrast theme.
    """
    icon = _TONE_ICONS[tone]
    line = f"{icon} **{label}:** {status_text}"
    if detail:
        line += f" — {detail}"
    st.markdown(line)


def render_status_summary(
    rows: list[tuple[str, str, StatusTone]], *, detail: dict[str, str] | None = None
) -> None:
    """Render several status lines in a fixed vertical stack.

    ``rows`` is ``(label, status_text, tone)`` tuples, in display order.
    ``detail`` optionally supplies a one-line explanation per label, keyed by
    the same ``label`` string.
    """
    detail = detail or {}
    for label, status_text, tone in rows:
        render_status_line(label, status_text, tone, detail=detail.get(label))
