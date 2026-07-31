#!/usr/bin/env python3
"""Reproducible lock-file generator for GeoTestLab.

Usage:
    python scripts/compile_requirements.py           # generate both lock files
    python scripts/compile_requirements.py --check    # verify committed files match
    python scripts/compile_requirements.py --check --diagnostics-dir lock-diagnostics
        # verify committed files, and when a lock mismatches copy the exact
        # generated workspace file and the exact unified diff (the same diff the
        # checker printed) into lock-diagnostics/ for CI to upload.

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

Diagnostics mode does not run a second, independent resolver pass: it
simply copies out the exact files and unified diffs that check() already
generated and compared.  The repository lock files are never modified by
check mode — generation happens only in the temporary workspace.
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


def _build_diff(committed: Path, generated: Path) -> str | None:
    """Return the unified diff between committed and generated lock files.

    Uses exactly the same comparison and diff the checker relies on.  Returns
    None when the two files are byte-for-byte identical.
    """
    committed_bytes = committed.read_bytes()
    generated_bytes = generated.read_bytes()

    if committed_bytes == generated_bytes:
        return None

    committed_lines = committed_bytes.decode("utf-8").splitlines(keepends=True)
    generated_lines = generated_bytes.decode("utf-8").splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            committed_lines,
            generated_lines,
            fromfile=f"committed/{committed.name}",
            tofile=f"generated/{generated.name}",
        )
    )


def _write_diagnostics(diagnostics_dir: Path, fname: str, workspace: Path) -> None:
    """Copy the exact generated lock file and its unified diff into the diagnostics dir.

    Copies the workspace-generated file byte-for-byte (``shutil.copy2``) and
    writes the same unified diff that ``check()`` compares with, so the
    uploaded diagnostics reproduce the failed checker workspace exactly.
    """
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    generated = workspace / fname
    if generated.exists():
        shutil.copy2(generated, diagnostics_dir / fname)

    diff_text = _build_diff(REPO_ROOT / fname, generated)
    if diff_text is not None:
        (diagnostics_dir / f"{fname}.diff").write_text(diff_text, encoding="utf-8")


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


def check(diagnostics_dir: str | Path | None = None) -> None:
    """Generate both lock files in a temp workspace and compare with committed files.

    Exits with code 1 when any lock mismatches.  Reports ALL mismatches
    before exiting.

    When ``diagnostics_dir`` is given and a lock mismatches, the exact
    workspace-generated lock file and the exact unified diff (the same diff
    printed here) are written into that directory for CI to upload.  The
    repository's committed lock files are never modified.
    """
    _check_python_version()

    mismatches: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        workspace = _prepare_workspace(tmp_path)
        diag_path = Path(diagnostics_dir) if diagnostics_dir is not None else None

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

            diff_text = _build_diff(committed, generated)

            if diff_text is None:
                print(f"  {fname}: OK")
            else:
                print(f"  {fname}: MISMATCH")
                mismatches.append(fname)
                for line in diff_text.splitlines(keepends=True):
                    print(f"    {line}", end="")
                if diag_path is not None:
                    _write_diagnostics(diag_path, fname, workspace)

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
    parser.add_argument(
        "--diagnostics-dir",
        metavar="PATH",
        default=None,
        help=(
            "With --check, copy the exact generated lock files and unified diffs for "
            "every mismatch into this directory (uploaded by CI on failure)."
        ),
    )
    args = parser.parse_args()

    if os.environ.get("CI"):
        print("Running in CI environment...")

    if args.check:
        check(diagnostics_dir=args.diagnostics_dir)
    elif args.diagnostics_dir:
        parser.error("--diagnostics-dir can only be used together with --check")
    else:
        generate()


if __name__ == "__main__":
    main()
