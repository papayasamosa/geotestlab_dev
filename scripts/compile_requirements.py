#!/usr/bin/env python3
"""Reproducible lock-file generator for GeoTestLab.

Usage:
    python scripts/compile_requirements.py          # generate both lock files
    python scripts/compile_requirements.py --check   # verify committed files match

Requires Python 3.11 and pip-tools >=7,<8.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPTOOLS = [sys.executable, "-m", "piptools", "compile"]

BASE_OPTS = [
    "--strip-extras",
    "--annotation-style=line",
    "--no-emit-index-url",
    "--no-emit-options",
    "--no-emit-trusted-host",
]


def _check_python_version() -> None:
    if sys.version_info[:2] != (3, 11):
        print(
            f"ERROR: Lock generation requires Python 3.11 (found {sys.version_info.major}.{sys.version_info.minor}).",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_piptools(output_file: str, extras: list[str]) -> bytes:
    cmd = (
        PIPTOOLS
        + BASE_OPTS
        + [f"--extra={e}" for e in extras]
        + ["--output-file", output_file]
        + ["pyproject.toml"]
    )
    print(f"  {' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=False,  # keep bytes to avoid encoding issues
    )
    if result.returncode != 0:
        error_text = result.stderr.decode("utf-8", errors="replace")
        # pip-compile exits 1 on warnings but the file is usually created
        # Only fail if the output file wasn't created
        if not (REPO_ROOT / output_file).exists():
            print(f"ERROR: {output_file} was not created.", file=sys.stderr)
            print(error_text, file=sys.stderr)
            sys.exit(1)
        print(f"  (pip-compile exited {result.returncode} but {output_file} was created)")
    return result.stdout


def generate() -> None:
    """Generate both lock files in the repository root."""
    _check_python_version()

    print("Generating requirements.txt (runtime + bayesian)...")
    _run_piptools("requirements.txt", extras=["bayesian"])

    print("Generating requirements-dev.txt (runtime + bayesian + dev)...")
    _run_piptools("requirements-dev.txt", extras=["bayesian", "dev"])

    print("Done.")


def check() -> None:
    """Generate both lock files in a temp dir and compare with committed files."""
    _check_python_version()

    with tempfile.TemporaryDirectory() as tmpdir:
        for fname, extras in [
            ("requirements.txt", ["bayesian"]),
            ("requirements-dev.txt", ["bayesian", "dev"]),
        ]:
            committed = REPO_ROOT / fname
            generated = Path(tmpdir) / fname

            print(f"Checking {fname}...")
            _run_piptools(str(generated), extras=extras)

            if not committed.exists():
                print(f"ERROR: {fname} is missing from the repository.", file=sys.stderr)
                sys.exit(1)

            committed_bytes = committed.read_bytes()
            generated_bytes = generated.read_bytes()

            if committed_bytes == generated_bytes:
                print(f"  {fname}: OK")
            else:
                print(f"  {fname}: MISMATCH")
                # Show unified diff
                import difflib

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
                sys.exit(1)

    print("All lock files are reproducible.")


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
