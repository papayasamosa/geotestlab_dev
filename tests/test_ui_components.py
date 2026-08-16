"""Focused coverage for the shared UI components (status, header, technical).

Follows the ``monkeypatch.setattr(module.st, ...)`` pattern already used in
``tests/test_power_ui.py`` rather than booting a full Streamlit ``AppTest``,
since these components are pure rendering helpers with no session-state
dependency.
"""

from __future__ import annotations

import geotestlab.ui.components.status as status_mod
import geotestlab.ui.components.summaries as summaries_mod
import geotestlab.ui.components.technical as technical_mod
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


def test_render_page_header_shows_title_and_subtitle(monkeypatch):
    headers = []
    captions = []
    monkeypatch.setattr(summaries_mod.st, "header", lambda text: headers.append(text))
    monkeypatch.setattr(summaries_mod.st, "caption", lambda text: captions.append(text))

    summaries_mod.render_page_header("Choose regions", "Select test and control regions")

    assert headers == ["Choose regions"]
    assert captions == ["Select test and control regions"]


def test_render_page_header_without_subtitle_skips_caption(monkeypatch):
    captions = []
    monkeypatch.setattr(summaries_mod.st, "header", lambda text: None)
    monkeypatch.setattr(summaries_mod.st, "caption", lambda text: captions.append(text))

    summaries_mod.render_page_header("Choose regions")

    assert captions == []


def test_render_next_action_is_a_single_primary_button(monkeypatch):
    seen = {}

    def fake_button(label, **kwargs):
        seen["label"] = label
        seen["kwargs"] = kwargs
        return True

    monkeypatch.setattr(summaries_mod.st, "button", fake_button)

    clicked = summaries_mod.render_next_action("Find regions", help_text="Runs matching")

    assert clicked is True
    assert seen["label"] == "Find regions"
    assert seen["kwargs"]["type"] == "primary"
    assert seen["kwargs"]["help"] == "Runs matching"


def test_render_technical_details_uses_a_collapsed_expander(monkeypatch):
    expander_calls = []

    class _FakeExpander:
        def __init__(self, title, expanded):
            expander_calls.append((title, expanded))

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    texts = []
    monkeypatch.setattr(technical_mod.st, "expander", _FakeExpander)
    monkeypatch.setattr(technical_mod.st, "text", lambda value: texts.append(value))

    technical_mod.render_technical_details(
        "Technical record", {"input_fingerprint": "3f8...", "tool_version": "1.2.3"}
    )

    assert expander_calls == [("Technical record", False)]
    assert any("input_fingerprint" in text for text in texts)
    assert any("tool_version" in text for text in texts)
