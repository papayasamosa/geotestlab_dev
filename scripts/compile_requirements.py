#!/usr/bin/env python3
"""Reproducible lock-file generator for GeoTestLab.

Usage:
    python scripts/compile_requirements.py          # generate both lock files
    python scripts/compile_requirements.py --check   # verify committed files match

Requires Python 3.11 and pip-tools >=7,<8.

Design
------
The check mode creates a temporary workspace containing copies of::

    pyproject.toml
    README.md
    requirements.txt
    requirements-dev.txt

It copies the committed locks into the workspace first so that
pip-compile's resolver sees the current pins.  The compile runs
from the workspace directory using relative output-file names,
so the generated header never contains an absolute temporary path.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Files that must exist in the temporary workspace
WORKSPACE_FILES = ["pyproject.toml", "README.md", "requirements.txt", "requirements-dev.txt"]

# Pip-compile base options
BASE_OPTS = [
    "--strip-extras",
    "--annotation-style=line",
    "--no-emit-index-url",
    "--no-emit-options",
    "--no-emit-trusted-host",
]

# Lock files and their extras
LOCK_SPECS: list[tuple[str, list[str]]] = [
    ("requirements.txt", ["bayesian"]),
    ("requirements-dev.txt", ["bayesian", "dev"]),
]


# ---------------------------------------------------------------------------
# Public API — imported by tests
# ---------------------------------------------------------------------------


def build_runtime_cmd(output_file: str = "requirements.txt") -> list[str]:
    """Build the pip-compile command for the runtime (bayesian) lock file."""
    return _build_cmd(output_file, ["bayesian"])


def build_dev_cmd(output_file: str = "requirements-dev.txt") -> list[str]:
    """Build the pip-compile command for the dev (bayesian + dev) lock file."""
    return _build_cmd(output_file, ["bayesian", "dev"])


def build_all_cmds() -> dict[str, list[str]]:
    """Return a dict mapping lock filename to its pip-compile command."""
    cmds: dict[str, list[str]] = {}
    for fname, extras in LOCK_SPECS:
        cmds[fname] = _build_cmd(fname, extras)
    return cmds


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_cmd(output_file: str, extras: list[str]) -> list[str]:
    """Construct the pip-compile command list."""
    return (
        [sys.executable, "-m", "piptools", "compile"]
        + BASE_OPTS
        + [f"--extra={e}" for e in extras]
        + ["--output-file", output_file]
        + ["pyproject.toml"]
    )


def _check_python_version() -> None:
    if sys.version_info[:2] != (3, 11):
        print(
            f"ERROR: Lock generation requires Python 3.11 "
            f"(found {sys.version_info.major}.{sys.version_info.minor}).",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_piptools(cmd: list[str], cwd: str | Path, label: str) -> None:
    """Run pip-compile with checked subprocess execution.

    Every non-zero exit causes an immediate failure.
    """
    print(f"  {' '.join(cmd)}")
    try:
        subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"ERROR: {label} timed out after 300 seconds.", file=sys.stderr)
        if exc.stdout:
            print(exc.stdout, file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, file=sys.stderr)
        print(exc.stderr, file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
    except FileNotFoundError as exc:
        print(f"ERROR: {label} command not found: {exc.filename}", file=sys.stderr)
        sys.exit(1)


def _prepare_workspace(tmpdir: Path) -> Path:
    """Create a temporary workspace with copies of required repo files.

    Returns the workspace Path.
    """
    workspace = tmpdir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    for fname in WORKSPACE_FILES:
        src = REPO_ROOT / fname
        if not src.exists():
            print(f"ERROR: {fname} is missing from the repository.", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(src, workspace / fname)

    return workspace


# ---------------------------------------------------------------------------
# Generation mode
# ---------------------------------------------------------------------------


def generate() -> None:
    """Generate both lock files in the repository root."""
    _check_python_version()

    for fname, extras in LOCK_SPECS:
        target = REPO_ROOT / fname
        # Delete any stale or partial file before generation
        if target.exists():
            target.unlink()
        print(f"Generating {fname} (extras: {extras})...")
        cmd = _build_cmd(fname, extras)
        _run_piptools(cmd, cwd=REPO_ROOT, label=fname)

    print("Done.")


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------


def check() -> None:
    """Generate both lock files in a temp workspace and compare with committed files.

    Exits with code 1 when any lock mismatches.  Reports ALL mismatches
    before exiting.
    """
    _check_python_version()

    mismatches: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        workspace = _prepare_workspace(tmp_path)

        for fname, extras in LOCK_SPECS:
            committed = REPO_ROOT / fname
            generated = workspace / fname

            print(f"Checking {fname}...")
            cmd = _build_cmd(fname, extras)
            _run_piptools(cmd, cwd=workspace, label=fname)

            if not generated.exists():
                print(f"ERROR: {fname} was not generated.", file=sys.stderr)
                mismatches.append(fname)
                continue

            committed_bytes = committed.read_bytes()
            generated_bytes = generated.read_bytes()

            if committed_bytes == generated_bytes:
                print(f"  {fname}: OK")
            else:
                print(f"  {fname}: MISMATCH")
                mismatches.append(fname)
                committed_lines = committed_bytes.decode("utf-8").splitlines(keepends=True)
                generated_lines = generated_bytes.decode("utf-8").splitlines(keepends=True)
                diff = difflib.unified_diff(
                    committed_lines,
                    generated_lines,
                    fromfile=f"committed/{fname}",
                    tofile=f"generated/{fname}",
                )
                for line in diff:
                    print(f"    {line}", end="")

        if mismatches:
            sys.exit(1)

    print("All lock files are reproducible.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify GeoTestLab lock files.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed lock files match freshly generated ones.",
    )
    args = parser.parse_args()

    if os.environ.get("CI"):
        print("Running in CI environment...")

    if args.check:
        check()
    else:
        generate()


if __name__ == "__main__":
    main()
