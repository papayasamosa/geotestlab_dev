"""Portable reproducibility metadata for local experiment records.

The experiment export deliberately contains identities and metadata, never raw
KPI observations or uploaded workbooks.  This module builds the metadata that
lets an analyst identify the code, dependency set, methodology, and source
files needed to reopen the record safely.
"""

from __future__ import annotations

import copy
import importlib.metadata
import platform
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from geotestlab.experiment.content import sha256_bytes
from geotestlab.experiment.fingerprints import compute_input_fingerprint
from geotestlab.experiment.identity import utc_now_iso
from geotestlab.experiment.version import tool_version

REPRODUCIBILITY_SCHEMA_VERSION = "experiment-reproducibility/v1"

DEFAULT_DISTRIBUTIONS = (
    "geotestlab",
    "streamlit",
    "pandas",
    "numpy",
    "scipy",
    "scikit-learn",
    "plotly",
    "altair",
    "openpyxl",
    "python-calamine",
)
DEFAULT_DEPENDENCY_FILES = ("requirements.txt", "requirements-dev.txt", "pyproject.toml")

SOURCE_LABELS = {
    "source_bytes": "uploaded KPI workbook",
    "analytical_data": "canonical analytical KPI data",
    "geography_workbook": "geography workbook",
    "market_sheet": "selected market sheet",
    "candidate_universe": "candidate region universe",
}


def installed_dependency_versions(names=DEFAULT_DISTRIBUTIONS) -> dict[str, str]:
    """Return installed versions without failing when an optional package is absent."""

    versions = {}
    for name in names:
        try:
            versions[str(name)] = importlib.metadata.version(str(name))
        except importlib.metadata.PackageNotFoundError:
            versions[str(name)] = "not-installed"
    return versions


def dependency_set_identity(
    project_root=None, filenames=DEFAULT_DEPENDENCY_FILES
) -> dict[str, object]:
    """Hash committed dependency declarations without exporting their contents."""

    root = Path(project_root) if project_root is not None else None
    files = []
    if root is not None:
        for filename in filenames:
            path = root / filename
            try:
                data = path.read_bytes()
            except OSError:
                continue
            files.append({"name": str(filename), "sha256": sha256_bytes(data)})
    file_hashes = {entry["name"]: entry["sha256"] for entry in files}
    lockfile = next((entry["name"] for entry in files if entry["name"] == "requirements.txt"), None)
    return {
        "fingerprint": compute_input_fingerprint(file_hashes) if file_hashes else None,
        "files": files,
        "lockfile": lockfile,
        "status": "recorded" if files else "unavailable",
    }


def _run_git(project_root, *arguments) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _safe_repository_url(value: str | None) -> str | None:
    """Normalise a remote URL while removing credentials and local-only detail."""

    if not value:
        return None
    raw = value.strip()
    if raw.startswith("git@") and ":" in raw:
        host, path = raw[4:].split(":", 1)
        return f"https://{host}/{path.removesuffix('.git')}"
    parsed = urlsplit(raw)
    if not parsed.hostname or not parsed.path:
        return None
    return urlunsplit(
        (parsed.scheme or "https", parsed.hostname, parsed.path.removesuffix(".git"), "", "")
    )


def repository_identity(project_root=None) -> dict[str, str | None]:
    """Return a safe repository/commit identity when the app runs from a checkout."""

    root = Path(project_root) if project_root is not None else Path.cwd()
    return {
        "repository": _safe_repository_url(_run_git(root, "remote", "get-url", "origin")),
        "commit": _run_git(root, "rev-parse", "HEAD"),
        "branch": _run_git(root, "branch", "--show-current"),
    }


def source_availability(
    required_digests=None, current_digests=None, source_names=None
) -> dict[str, object]:
    """Compare recorded source identities with the sources currently available.

    ``current_digests=None`` means no source has been restored.  A source is
    never considered restored merely because its digest was recorded in JSON.
    """

    required = {
        str(key): value
        for key, value in (required_digests or {}).items()
        if value not in (None, "")
    }
    current = current_digests or {}
    missing = []
    changed = []
    matched = []
    for key, expected in required.items():
        label = SOURCE_LABELS.get(key, key)
        name = (source_names or {}).get(key)
        if name:
            display_name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
            label = f"{label} ({display_name})"
        actual = current.get(key)
        if actual in (None, ""):
            missing.append(label)
        elif actual != expected:
            changed.append(label)
        else:
            matched.append(label)
    if not required:
        status = "not_recorded"
    elif missing:
        status = "missing"
    elif changed:
        status = "changed"
    else:
        status = "available"
    return {
        "status": status,
        "missing": missing,
        "changed": changed,
        "matched": matched,
        "required_count": len(required),
    }


def build_reproducibility_metadata(
    *,
    project_root=None,
    source_digests=None,
    current_source_digests=None,
    methodology_version=None,
    evidence_suite_version=None,
    source_names=None,
    loaded_from_export=False,
) -> dict:
    """Build a JSON-safe, non-sensitive reproducibility envelope."""

    required_digests = {
        str(key): value for key, value in (source_digests or {}).items() if value not in (None, "")
    }
    source = source_availability(required_digests, current_source_digests, source_names)
    source.update(
        {
            "embedded": False,
            "required_digests": required_digests,
            "source_names": dict(source_names or {}),
            "reload_requirement": (
                "Re-upload or otherwise restore matching source files before recomputing."
                if required_digests
                else "No source-data digest was recorded."
            ),
        }
    )
    return {
        "schema_version": REPRODUCIBILITY_SCHEMA_VERSION,
        "loaded_from_export": bool(loaded_from_export),
        "tool": {
            "package": "geotestlab",
            "version": tool_version(),
            **repository_identity(project_root),
        },
        "runtime": {
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "dependencies": {
            "versions": installed_dependency_versions(),
            "dependency_set": dependency_set_identity(project_root),
        },
        "methodology": {
            "power_methodology_version": methodology_version,
            "evidence_suite_version": evidence_suite_version,
        },
        "source_data": source,
    }


def mark_loaded_from_export(metadata: dict | None, current_source_digests=None, now=None) -> dict:
    """Annotate imported metadata without claiming that source data was restored."""

    loaded = copy.deepcopy(metadata or {})
    loaded["loaded_from_export"] = True
    source = dict(loaded.get("source_data") or {})
    required = dict(source.get("required_digests") or {})
    availability = source_availability(
        required, current_source_digests, source.get("source_names") or {}
    )
    source["current_availability"] = availability
    source["load_status"] = "source_files_required" if required else "source_data_not_recorded"
    loaded["source_data"] = source
    loaded["load"] = {
        "loaded_at": utc_now_iso(now),
        "source_status": availability["status"],
        "missing_sources": list(availability["missing"]),
        "changed_sources": list(availability["changed"]),
        "analytical_state_restored": False,
    }
    return loaded
