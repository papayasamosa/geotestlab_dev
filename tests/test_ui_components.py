"""Focused coverage for the shared status-line UI component.

Follows the ``monkeypatch.setattr(module.st, ...)`` pattern already used in
``tests/test_power_ui.py`` rather than booting a full Streamlit ``AppTest``,
since this component is a pure rendering helper with no session-state
dependency.
"""

from __future__ import annotations

import geotestlab.ui.components.status as status_mod
from geotestlab.ui.components import StatusTone


def test_render_status_line_includes_icon_label_status_and_detail(monkeypatch):
    calls = []
    monkeypatch.setattr(status_mod.st, "markdown", lambda text: calls.append(text))

    status_mod.render_status_line(
        "Match quality", "Good", StatusTone.GOOD, detail="See balance table"
    )

    assert len(calls) == 1
    assert "Match quality" in calls[0]
    assert "Good" in calls[0]
    assert "See balance table" in calls[0]
    assert calls[0].startswith("✅")


def test_render_status_line_never_relies_on_colour_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(status_mod.st, "markdown", lambda text: calls.append(text))

    for tone in StatusTone:
        status_mod.render_status_line("Stage", "Status text", tone)

    assert len(calls) == len(list(StatusTone))
    leading_icons = {call[0] for call in calls}
    assert len(leading_icons) == len(list(StatusTone))


def test_render_status_summary_renders_each_row_with_matching_detail(monkeypatch):
    calls = []
    monkeypatch.setattr(status_mod.st, "markdown", lambda text: calls.append(text))
    rows = [
        ("Match quality", "Good", StatusTone.GOOD),
        ("Power", "Below target", StatusTone.WARNING),
    ]

    status_mod.render_status_summary(rows, detail={"Power": "Needs a larger test area"})

    assert len(calls) == 2
    assert "Needs a larger test area" not in calls[0]
    assert "Needs a larger test area" in calls[1]
