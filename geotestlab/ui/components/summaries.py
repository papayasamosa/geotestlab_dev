"""Page-header and primary-next-action components shared across pages.

See the UX overhaul programme, section 5.5: one primary action per step.
"""

from __future__ import annotations

import streamlit as st


def render_page_header(title: str, subtitle: str | None = None) -> None:
    """Render a page title with an optional one-line subtitle."""
    st.header(title)
    if subtitle:
        st.caption(subtitle)


def render_next_action(
    label: str,
    *,
    help_text: str | None = None,
    key: str | None = None,
    disabled: bool = False,
) -> bool:
    """Render the single primary action for a step. Returns ``True`` when clicked.

    Only one ``render_next_action`` should be visible per step; secondary
    downloads and technical actions must not compete with it visually.
    """
    return st.button(label, help=help_text, key=key, type="primary", disabled=disabled)
