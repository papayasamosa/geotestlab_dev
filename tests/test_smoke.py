"""Startup and baseline safety tests for GeoTestLab.

These tests verify the live Streamlit application starts correctly, dependency
files are portable, and the production app is syntactically valid.
"""

from __future__ import annotations

import json
import py_compile
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Golden schema — all golden files must contain these fields
# ---------------------------------------------------------------------------

REQUIRED_GOLDEN_FIELDS = [
    "schema_version",
    "scenario",
    "fixture_version",
    "app_baseline_commit",
    "golden_created_by_commit",
    "settings",
    "expected",
    "tolerances",
    "known_limitations",
]

# Scenario-specific expected keys
SCENARIO_EXPECTED_KEYS = {
    "app_tab_labels": {"n_tabs", "tab_labels"},
    "bundled_workbook_structure": {"n_sheets", "sheet_names"},
    "available_markets": {"markets", "default_market"},
}

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_golden_schema(data: dict, filename: str) -> list[str]:
    """Validate a golden file's schema. Returns list of errors (empty = valid)."""
    errors: list[str] = []

    # Check required fields present
    for field in REQUIRED_GOLDEN_FIELDS:
        if field not in data:
            errors.append(f"{filename}: missing field '{field}'")

    if errors:
        return errors

    # Schema version
    if data["schema_version"] != 1:
        errors.append(f"{filename}: schema_version must be 1, got {data['schema_version']}")

    # Scenario
    if not isinstance(data["scenario"], str) or not data["scenario"]:
        errors.append(f"{filename}: scenario must be a non-empty string")
    elif data["scenario"] != filename.replace(".json", ""):
        errors.append(f"{filename}: scenario '{data['scenario']}' does not match filename")

    # Fixture version
    if not isinstance(data["fixture_version"], int) or data["fixture_version"] < 1:
        errors.append(f"{filename}: fixture_version must be a positive integer")

    # Commit fields must be full 40-char SHAs
    for commit_field in ["app_baseline_commit", "golden_created_by_commit"]:
        val = data.get(commit_field, "")
        if not FULL_SHA_RE.match(val):
            errors.append(f"{filename}: {commit_field} is not a 40-char hex SHA: {val}")

    # settings must be a dict
    if not isinstance(data.get("settings"), dict):
        errors.append(f"{filename}: settings must be a dict")

    # expected must be a dict
    if not isinstance(data.get("expected"), dict):
        errors.append(f"{filename}: expected must be a dict")

    # tolerances must be a dict
    if not isinstance(data.get("tolerances"), dict):
        errors.append(f"{filename}: tolerances must be a dict")

    # known_limitations must be a list of strings
    kl = data.get("known_limitations")
    if not isinstance(kl, list) or not all(isinstance(item, str) for item in kl):
        errors.append(f"{filename}: known_limitations must be a list of strings")

    # Scenario-specific required keys in expected
    scenario = data.get("scenario", "")
    if scenario in SCENARIO_EXPECTED_KEYS:
        expected = data.get("expected", {})
        for key in SCENARIO_EXPECTED_KEYS[scenario]:
            if key not in expected:
                errors.append(f"{filename}: expected missing key '{key}' for scenario '{scenario}'")

    return errors


def _load_golden(name: str) -> dict:
    """Load a golden file. Tests fail if the file is missing."""
    path = REPO_ROOT / "tests" / "golden" / f"{name}.json"
    assert path.exists(), (
        f"Golden file {path.name} not found. "
        f"Run 'python scripts/update_goldens.py --approve' to create it."
    )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Syntax / compilation tests
# ---------------------------------------------------------------------------


class TestMainAppSyntax:
    """The main Streamlit app must be syntactically valid Python."""

    @pytest.mark.smoke
    def test_main_app_compiles(self):
        main_path = REPO_ROOT / "geotestmatch.py"
        assert main_path.is_file(), f"Main app not found at {main_path}"
        py_compile.compile(str(main_path), doraise=True)


# ---------------------------------------------------------------------------
# Live Streamlit app tests (using conftest live_app fixture)
# ---------------------------------------------------------------------------


class TestLiveAppStartup:
    """End-to-end tests against the live Streamlit application."""

    @pytest.mark.smoke
    def test_live_app_starts(self, live_app):
        assert not live_app.exception, f"App raised: {live_app.exception}"

    @pytest.mark.smoke
    def test_exact_title(self, live_app):
        assert len(live_app.title) > 0
        assert live_app.title[0].value == "TEST GeoTestLab"

    @pytest.mark.smoke
    def test_exact_tab_labels(self, live_app):
        tab_labels = [t.label for t in live_app.tabs]
        assert tab_labels == [
            "\u2699\ufe0f Region Matching",
            "\U0001f50d Validate Test Design",
            "\U0001f4ca Measure Test Impact",
            "\U0001f9e0 Bayesian TBR",
            "\U0001f4c8 Power & Test Sizing",
            "\U0001f4e3 Media Delivery Feasibility",
            "\U0001f3af Effect Plausibility",
            "\u2705 Integrated Design Recommendation",
        ]

    @pytest.mark.smoke
    def test_market_selectbox_label(self, live_app):
        selectboxes = [s for s in live_app.sidebar.selectbox if "Market" in s.label]
        assert len(selectboxes) > 0, "No selectbox with 'Market' label found"

    @pytest.mark.smoke
    def test_sidebar_renders(self, live_app):
        assert live_app.sidebar is not None


# ---------------------------------------------------------------------------
# Bundled data file tests
# ---------------------------------------------------------------------------


class TestBundledData:
    """Verify the bundled demographic workbook exists at the expected path."""

    @pytest.mark.smoke
    def test_bundled_data_file_exists(self):
        data_path = (
            REPO_ROOT
            / "data"
            / "Population Stats for Geo Tests - Master Sheet Only v2 (Standardised).xlsx"
        )
        assert data_path.exists(), f"Bundled workbook not found: {data_path}"


# ---------------------------------------------------------------------------
# Dependency file portability
# ---------------------------------------------------------------------------


class TestDependencyFilesPortability:
    """Dependency files must be portable and contain no local paths."""

    @pytest.mark.smoke
    def test_no_local_paths_in_requirements(self):
        for fname in ["requirements.txt", "requirements-dev.txt"]:
            path = REPO_ROOT / fname
            assert path.exists(), f"{fname} is missing"
            content = path.read_text(encoding="utf-8")
            for pattern in ["file:///", "C:/", "C:\\", "/Users/", "/home/"]:
                assert pattern not in content, f"{fname} contains {pattern}"


# ---------------------------------------------------------------------------
# Golden file schema validation (strict)
# ---------------------------------------------------------------------------


class TestGoldenSchema:
    """All golden files must contain the required schema fields with valid values."""

    @pytest.mark.smoke
    def test_golden_files_have_valid_schema(self):
        golden_dir = REPO_ROOT / "tests" / "golden"
        json_files = sorted(golden_dir.glob("*.json"))
        assert len(json_files) > 0, "No golden files found"

        all_errors: list[str] = []
        for gf in json_files:
            data = json.loads(gf.read_text(encoding="utf-8"))
            all_errors.extend(_validate_golden_schema(data, gf.name))

        assert not all_errors, "Golden schema validation failed:\n  " + "\n  ".join(all_errors)

    @pytest.mark.smoke
    def test_scenario_names_are_unique(self):
        golden_dir = REPO_ROOT / "tests" / "golden"
        json_files = sorted(golden_dir.glob("*.json"))
        scenarios = []
        for gf in json_files:
            data = json.loads(gf.read_text(encoding="utf-8"))
            scenarios.append(data["scenario"])
        assert len(scenarios) == len(set(scenarios)), f"Duplicate scenario names: {scenarios}"

    @pytest.mark.smoke
    def test_golden_files_are_read_only(self):
        """Tests must fail when a golden file is missing — no auto-creation."""
        for name in ["app_tab_labels", "bundled_workbook_structure", "available_markets"]:
            path = REPO_ROOT / "tests" / "golden" / f"{name}.json"
            assert path.exists(), (
                f"Golden file {path.name} is missing. "
                f"Tests must NOT create it — run 'python scripts/update_goldens.py --approve'"
            )


# ---------------------------------------------------------------------------
# Lock reproducibility (via compile_requirements.py --check)
# ---------------------------------------------------------------------------


class TestLockReproducibility:
    """Lock files must be reproducible from the canonical command."""

    @pytest.mark.smoke
    def test_lock_files_have_no_bom(self):
        for fname in ["requirements.txt", "requirements-dev.txt"]:
            path = REPO_ROOT / fname
            assert path.exists(), f"{fname} is missing"
            content = path.read_bytes()
            # UTF-8 BOM is EF BB BF
            assert not (content[:3] == b"\xef\xbb\xbf"), f"{fname} has a byte-order mark"

    @pytest.mark.smoke
    def test_compile_script_constructs_correct_args(self):
        """Verify the compile script produces the expected pip-compile commands."""
        from scripts.compile_requirements import build_dev_cmd, build_runtime_cmd

        # Test runtime command
        runtime_cmd = build_runtime_cmd()
        assert "--extra=bayesian" in " ".join(runtime_cmd)
        assert "--output-file" in " ".join(runtime_cmd)
        assert "requirements.txt" in " ".join(runtime_cmd)

        # Test dev command
        dev_cmd = build_dev_cmd()
        assert "--extra=bayesian" in " ".join(dev_cmd)
        assert "--extra=dev" in " ".join(dev_cmd)
        assert "requirements-dev.txt" in " ".join(dev_cmd)

    @pytest.mark.smoke
    def test_compile_script_checks_python_version(self):
        """The compile script must require Python 3.11 (source inspection)."""
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr._check_python_version)
        assert "sys.version_info[:2]" in source
        assert "(3, 11)" in source
        assert "sys.exit(1)" in source

        # On Python 3.11 the function should pass; on any other version it exits.
        if sys.version_info[:2] == (3, 11):
            # Should not raise
            cr._check_python_version()
        else:
            with pytest.raises(SystemExit):
                cr._check_python_version()


# ---------------------------------------------------------------------------
# Python version guard
# ---------------------------------------------------------------------------


class TestPythonVersion:
    """GeoTestLab targets Python 3.11 only."""

    @pytest.mark.smoke
    def test_python_version_is_311(self):
        if sys.version_info[:2] != (3, 11):
            pytest.xfail(f"Python {sys.version_info.major}.{sys.version_info.minor} is not 3.11")
        assert sys.version_info[:2] == (3, 11)
