"""Live tests for the shared time-series tracking-outage exclusion widget
(Design/Evaluate tabs). Drives the real app via
tests.fixtures.live_scenarios.drive_outage_exclusion() with a fixture that
has one injected market-wide zero week on top of otherwise-clean correlated
data. Asserts behaviour directly (no golden comparison — this is new
behaviour with no golden file yet).
"""

from __future__ import annotations

import pytest

from tests.fixtures.live_scenarios import drive_outage_exclusion


@pytest.mark.slow
class TestTimeSeriesOutageExclusion:
    @classmethod
    @pytest.fixture(scope="class")
    def result(cls, tmp_path_factory):
        return drive_outage_exclusion(tmp_path_factory.mktemp("outage"))

    def test_no_exception(self, result):
        assert not result["exception"], result.get("errors")

    def test_injected_outage_week_is_preselected(self, result):
        assert result["outage_date_preselected"] is True

    def test_selection_survives_an_unrelated_rerun(self, result):
        assert result["value_persisted_before_run_click"] is True

    def test_selection_survives_the_run_button_click(self, result):
        assert result["value_persisted_after_run_click"] is True

    def test_recorded_as_automatic_and_effective_exclusion(self, result):
        assert result["n_preselected"] == 1
        assert len(result["automatic_outage_dates"]) == 1
        assert result["manual_excluded_dates"] == result["automatic_outage_dates"]
        assert result["effective_excluded_dates"] == result["automatic_outage_dates"]
