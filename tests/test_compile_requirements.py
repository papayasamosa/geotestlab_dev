"""Tests for the compile_requirements.py lock reproducibility script.

These tests verify the command builder, Python version guard, workspace
preparation, and diff reporting logic without actually running pip-compile
(which would be slow and environment-dependent).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture: manual temp dir to avoid Windows PermissionError with tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    """Yield a temporary directory, cleaning up afterward."""
    import shutil

    tmp = tempfile.mkdtemp()
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Command builder tests
# ---------------------------------------------------------------------------


class TestCommandBuilder:
    """Verify the command builder produces the expected pip-compile commands."""

    def test_build_runtime_cmd(self):
        from scripts.compile_requirements import build_runtime_cmd

        cmd = build_runtime_cmd()
        assert isinstance(cmd, list)
        assert all(isinstance(part, str) for part in cmd)
        assert "piptools" in " ".join(cmd)
        assert "compile" in cmd
        assert "--extra=bayesian" in cmd
        assert "--strip-extras" in cmd
        assert "--annotation-style=line" in cmd
        assert "--output-file" in cmd
        assert "requirements.txt" in cmd[cmd.index("--output-file") + 1]
        assert "pyproject.toml" in cmd

    def test_build_dev_cmd(self):
        from scripts.compile_requirements import build_dev_cmd

        cmd = build_dev_cmd()
        assert isinstance(cmd, list)
        assert "--extra=bayesian" in cmd
        assert "--extra=dev" in cmd
        assert "--output-file" in cmd
        dev_idx = cmd.index("--output-file") + 1
        assert "requirements-dev.txt" == cmd[dev_idx]

    def test_build_all_cmds(self):
        from scripts.compile_requirements import build_all_cmds

        cmds = build_all_cmds()
        assert isinstance(cmds, dict)
        assert "requirements.txt" in cmds
        assert "requirements-dev.txt" in cmds
        assert len(cmds) == 2

    def test_commands_use_relative_output_names(self):
        """Output file names must be relative, not absolute paths."""
        from scripts.compile_requirements import build_dev_cmd, build_runtime_cmd

        for builder in [build_runtime_cmd, build_dev_cmd]:
            cmd = builder()
            out_idx = cmd.index("--output-file") + 1
            out_name = cmd[out_idx]
            # Must be a simple filename, not an absolute path
            assert "/" not in out_name, f"Output name is absolute: {out_name}"
            assert "\\" not in out_name, f"Output name is absolute: {out_name}"
            assert out_name.endswith(".txt")

    def test_commands_include_no_emit_flags(self):
        from scripts.compile_requirements import build_runtime_cmd

        cmd = " ".join(build_runtime_cmd())
        assert "--no-emit-index-url" in cmd
        assert "--no-emit-options" in cmd
        assert "--no-emit-trusted-host" in cmd


# ---------------------------------------------------------------------------
# Python version guard tests
# ---------------------------------------------------------------------------


class TestPythonVersionGuard:
    """The _check_python_version function must enforce Python 3.11."""

    def test_guard_exists(self):
        import scripts.compile_requirements as cr

        assert hasattr(cr, "_check_python_version")
        assert callable(cr._check_python_version)

    def test_guard_passes_on_311(self):
        import scripts.compile_requirements as cr

        if sys.version_info[:2] == (3, 11):
            cr._check_python_version()
        else:
            pytest.skip("Not running on Python 3.11")

    def test_guard_checks_version_tuple(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr._check_python_version)
        assert "sys.version_info[:2]" in source
        assert "(3, 11)" in source
        assert "sys.exit(1)" in source


# ---------------------------------------------------------------------------
# Workspace preparation tests
# ---------------------------------------------------------------------------


class TestWorkspacePreparation:
    """Verify the temp workspace is set up correctly."""

    def test_prepare_workspace_creates_files(self, tmp_dir):
        from scripts.compile_requirements import _prepare_workspace

        workspace = _prepare_workspace(tmp_dir)
        assert workspace.exists()
        assert workspace.is_dir()
        assert (workspace / "pyproject.toml").exists()
        assert (workspace / "README.md").exists()
        assert (workspace / "requirements.txt").exists()
        assert (workspace / "requirements-dev.txt").exists()

    def test_prepare_workspace_files_are_copies(self, tmp_dir):
        from scripts.compile_requirements import REPO_ROOT, _prepare_workspace

        workspace = _prepare_workspace(tmp_dir)
        for fname in ["pyproject.toml", "README.md", "requirements.txt", "requirements-dev.txt"]:
            src = REPO_ROOT / fname
            dst = workspace / fname
            assert dst.exists()
            assert dst.read_bytes() == src.read_bytes(), (
                f"{fname} content differs between workspace and repo"
            )

    def test_prepare_workspace_exits_on_missing_file(self, tmp_dir):
        from scripts.compile_requirements import REPO_ROOT, _prepare_workspace

        missing = REPO_ROOT / "README.md"
        backup = REPO_ROOT / "README.md.bak"
        try:
            if missing.exists():
                missing.rename(backup)
            with pytest.raises(SystemExit):
                _prepare_workspace(tmp_dir)
        finally:
            if backup.exists():
                backup.rename(missing)


# ---------------------------------------------------------------------------
# Subprocess error handling tests
# ---------------------------------------------------------------------------


class TestSubprocessErrorHandling:
    """Verify that _run_piptools strictly enforces subprocess success."""

    def test_run_piptools_uses_checked_execution(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr._run_piptools)
        assert "check=True" in source, "Must use check=True for subprocess.run"
        assert "subprocess.CalledProcessError" in source
        assert "subprocess.TimeoutExpired" in source

    def test_run_piptools_rejects_nonzero_exit(self, tmp_dir):
        """When pip-compile returns non-zero, _run_piptools must raise SystemExit."""
        import scripts.compile_requirements as cr

        cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
        with pytest.raises(SystemExit) as exc_info:
            cr._run_piptools(cmd, cwd=tmp_dir, label="test")
        assert exc_info.value.code == 1

    def test_run_piptools_rejects_missing_command(self, tmp_dir):
        import scripts.compile_requirements as cr

        cmd = ["nonexistent-command-that-will-fail"]
        with pytest.raises(SystemExit):
            cr._run_piptools(cmd, cwd=tmp_dir, label="missing")

    def test_run_piptools_includes_file_not_found(self):
        """Must handle FileNotFoundError for missing executables."""
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr._run_piptools)
        assert "FileNotFoundError" in source

    def test_run_piptools_does_not_accept_output_file_existence(self, tmp_dir):
        """A non-zero exit must fail even when an output file happens to exist."""
        import scripts.compile_requirements as cr

        (tmp_dir / "dummy.txt").write_text("fake content")
        cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
        with pytest.raises(SystemExit):
            cr._run_piptools(cmd, cwd=tmp_dir, label="no-tolerance")


# ---------------------------------------------------------------------------
# Lock comparison logic tests
# ---------------------------------------------------------------------------


class TestLockComparison:
    """Verify the check() function reports diffs correctly."""

    def test_both_diffs_reported(self):
        """The check() function must collect both diffs before exiting."""
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr.check)
        assert "mismatches" in source
        assert "mismatches.append" in source
        assert "if mismatches:" in source
        assert "sys.exit(1)" in source


# ---------------------------------------------------------------------------
# Generation mode tests
# ---------------------------------------------------------------------------


class TestGenerationMode:
    """Verify the generate() function."""

    def test_generate_checks_python_version(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr.generate)
        assert "_check_python_version()" in source

    def test_generate_deletes_stale_files_first(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr.generate)
        assert "target.unlink()" in source or "target.exists()" in source


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestCLI:
    """Verify the CLI entry point."""

    def test_main_has_check_flag(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr.main)
        assert "--check" in source

    def test_main_calls_generate_or_check(self):
        import inspect

        import scripts.compile_requirements as cr

        source = inspect.getsource(cr.main)
        assert "args.check" in source
        assert "generate()" in source or "check()" in source
