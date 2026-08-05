"""Authoritative tool version derived from installed package metadata.

The tool version recorded in frozen design snapshots and exports must not be
hardcoded: it is read from the installed ``geotestlab`` distribution (which
mirrors ``pyproject.toml``'s ``version``), with a documented, tested
development fallback when the package is not installed as a distribution
(e.g. a plain source checkout).
"""

from __future__ import annotations

import importlib.metadata

_PACKAGE_NAME = "geotestlab"

# Development fallback when ``geotestlab`` is not installed as a distribution.
# Documented and tested: callers always receive a string.
DEV_TOOL_VERSION = "0.0.0+dev"


def tool_version() -> str:
    """The authoritative tool version from installed package metadata.

    Returns the installed distribution version (which must match
    ``pyproject.toml``'s ``version``) or :data:`DEV_TOOL_VERSION` when the
    package is not installed, so callers always get a usable string.
    """
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return DEV_TOOL_VERSION
