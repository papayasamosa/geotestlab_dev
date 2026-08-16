"""Collapsed technical/reproducibility detail, kept out of the normal path.

See the UX overhaul programme, section 7: fingerprints, hashes, commit
identity and other implementation-only values must never appear in the
normal analyst UI outside a component like this one.
"""

from __future__ import annotations

from typing import Mapping

import streamlit as st


def render_technical_details(title: str, details: Mapping[str, object]) -> None:
    """Render developer/reproducibility metadata inside a collapsed expander."""
    with st.expander(title, expanded=False):
        for key, value in details.items():
            st.text(f"{key}: {value}")
