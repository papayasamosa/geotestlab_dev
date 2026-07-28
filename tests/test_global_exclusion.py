"""Live tests for the global 'exclude from both test and control' widget.

Drives the real app (no internal function calls) via
tests.fixtures.live_scenarios.drive_global_exclusion(). Asserts behaviour
directly rather than via golden comparison, since this is new behaviour
with no golden file yet — goldens are only added/updated once the change
has been reviewed (see tests/fixtures/live_scenarios.py's Stage 4 docstring
convention).
"""

from __future__ import annotations

import pytest

from tests.fixtures.live_scenarios import drive_global_exclusion


@pytest.mark.slow
class TestGlobalExclusion:
    @classmethod
    @pytest.fixture(scope="class")
    def result(cls):
        return drive_global_exclusion()

    def test_no_exception(self, result):
        assert not result["exception"], result.get("errors")

    def test_selection_survives_an_unrelated_rerun(self, result):
        assert result["value_persisted_before_run_click"] is True

    def test_selection_survives_the_run_button_click(self, result):
        assert result["value_persisted_after_run_click"] is True

    def test_excluded_from_control_candidate_pool(self, result):
        """Proves absence from the actual candidate pool used for control
        selection, not just from the final selected controls — the gap the
        existing constraints golden explicitly does not cover."""
        assert result["excluded_from_control_candidate_pool"] is True

    def test_excluded_from_final_test_group(self, result):
        assert result["excluded_from_final_test_group"] is True

    def test_excluded_from_final_control_group(self, result):
        assert result["excluded_from_final_control_group"] is True

    def test_recorded_in_run_snapshot(self, result):
        assert result["snapshot_global_exclusions"] == [result["excluded_geo"]]
