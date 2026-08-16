"""Stage 3B: Bayesian state lifecycle — trace creation and reset families.

AppTest coverage:
- a real (reduced-sampling) Bayesian run stores ``bayesian_trace`` alongside
  ``bayesian_results`` (trace creation; runs in the ``bayesian-smoke (3.11)``
  CI job, not the fast suite);
- every reset family REMOVES the ``bayesian_trace`` key (so the potentially
  large InferenceData object can be garbage-collected) while clearing
  ``bayesian_results``: matching reset (``reset_results``), manual reset
  (``reset_manual_results``), validation reset (``clear_validation_state``),
  and file change (``clear_uploaded_kpi_state``).

The pure reduced-sampling smoke (real PyMC sampling) lives in
``tests/test_bayesian_core.py::TestReducedSamplingSmoke``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from geotestlab.ui import PlanStep
from tests.conftest import seed_evaluate, seed_plan_step
from tests.fixture_factories.write_correlated_kpi_xlsx import write_correlated_kpi_xlsx
from tests.fixtures.live_scenarios import (
    CONTROL_REGIONS,
    RUN_TIMEOUT,
    TEST_REGION,
    _manual_match,
    _upload_kpi,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(REPO_ROOT / "geotestmatch.py")


def _new_app() -> AppTest:
    app = AppTest.from_file(APP_PATH)
    seed_plan_step(app, PlanStep.REGIONS)
    app.run(timeout=RUN_TIMEOUT)
    return app


def _inject_bayesian_state(app: AppTest) -> None:
    """Simulate a completed Bayesian result + trace (no real sampling)."""
    app.session_state["bayesian_results"] = {"mean_uplift": 1.0, "uplift_pct": 0.5}
    app.session_state["bayesian_trace"] = object()
    app.session_state["bayesian_interpretation_visible"] = True


def _assert_trace_cleared(app: AppTest) -> None:
    assert "bayesian_trace" not in app.session_state
    assert app.session_state["bayesian_results"] is None


# ---------------------------------------------------------------------------
# Trace creation (real path, reduced sampling) — slow, runs in bayesian-smoke CI
# ---------------------------------------------------------------------------
@pytest.mark.slow
class TestBayesianTraceCreation:
    def test_real_run_stores_trace(self, tmp_path: Path):
        """A completed Bayesian run stores the posterior trace in session state
        alongside the serialisable results (Evaluate mode so a test period
        exists). Uses a tiny sampling profile so the real PyMC path completes
        quickly; this is an execution-path smoke, not convergence evidence."""
        kpi_path = write_correlated_kpi_xlsx(
            tmp_path / "weekly_eval.xlsx",
            TEST_REGION,
            CONTROL_REGIONS,
            metric_name="Sales",
            n_periods=60,
            freq="W",
            seed=123,
        )
        app = _new_app()
        _manual_match(app)
        # Measure Test Impact and the Bayesian TBR button both live under the
        # Evaluate journey (the "tab7" slot); the Bayesian button is
        # additionally gated behind the "advanced uncertainty" toggle within
        # Results.
        seed_evaluate(app, show_advanced_uncertainty=True)
        app.run(timeout=RUN_TIMEOUT)
        _upload_kpi(app, "evaluate", "weekly_eval.xlsx", kpi_path.read_bytes())

        run_btn = [b for b in app.button if b.key == "evaluate_run_button"][0]
        run_btn.click()
        app.run(timeout=RUN_TIMEOUT)
        assert app.session_state["validation_results"] is not None

        # Reduced sampling profile (draws=20/tune=10/chains=1).
        app.session_state["bayes_mcmc_draws"] = 20
        app.session_state["bayes_mcmc_tune"] = 10
        app.session_state["bayes_mcmc_chains"] = 1
        bayes_btn = [b for b in app.button if b.key == "run_bayesian_tbr"][0]
        assert bayes_btn.disabled is False
        bayes_btn.click()
        app.run(timeout=RUN_TIMEOUT)

        assert "bayesian_trace" in app.session_state
        assert app.session_state["bayesian_trace"] is not None
        assert app.session_state["bayesian_results"] is not None
        assert app.session_state["bayesian_interpretation_visible"] is True

        # Guard: if the trace is dropped while results are still present (e.g. a
        # future reset path forgets it), the results view must not crash — a
        # caption explains that MCMC diagnostics are unavailable.
        del app.session_state["bayesian_trace"]
        app.run(timeout=RUN_TIMEOUT)
        assert "bayesian_trace" not in app.session_state
        assert app.session_state["bayesian_results"] is not None
        captions = [c.value for c in app.caption]
        assert any("MCMC diagnostics" in c for c in captions)


# ---------------------------------------------------------------------------
# Every reset family removes the trace key alongside clearing the results
# ---------------------------------------------------------------------------
class TestResetFamiliesClearTrace:
    def test_matching_reset_clears_trace(self):
        app = _new_app()
        _inject_bayesian_state(app)
        # Changing the market fires reset_results (matching reset family).
        market_sb = [s for s in app.selectbox if s.label == "Market"][0]
        market_sb.set_value(market_sb.options[1])
        app.run(timeout=RUN_TIMEOUT)
        _assert_trace_cleared(app)

    def test_manual_reset_clears_trace(self):
        app = _new_app()
        setup_radio = [r for r in app.radio if r.label == "Setup Mode"][0]
        if setup_radio.value != setup_radio.options[0]:
            setup_radio.set_value(setup_radio.options[0])  # manual selection mode
            app.run(timeout=RUN_TIMEOUT)
        test_ms = [m for m in app.multiselect if m.label == "test_geos_manual"][0]
        _inject_bayesian_state(app)
        test_ms.set_value([test_ms.options[0]])  # fires reset_manual_results
        app.run(timeout=RUN_TIMEOUT)
        _assert_trace_cleared(app)

    def test_validation_reset_clears_trace(self, tmp_path: Path):
        kpi_path = write_correlated_kpi_xlsx(
            tmp_path / "weekly.xlsx",
            TEST_REGION,
            CONTROL_REGIONS,
            metric_name="Sales",
            n_periods=60,
            freq="W",
            seed=123,
        )
        app = _new_app()
        _manual_match(app)
        seed_plan_step(app, PlanStep.CHECK_DESIGN)
        app.run(timeout=RUN_TIMEOUT)
        _upload_kpi(app, "design", "weekly.xlsx", kpi_path.read_bytes())
        _inject_bayesian_state(app)
        # Changing the historical-period start fires clear_validation_state.
        start_sb = [s for s in app.selectbox if s.key == "design_design_start"][0]
        start_sb.set_value(start_sb.options[len(start_sb.options) // 2])
        app.run(timeout=RUN_TIMEOUT)
        _assert_trace_cleared(app)

    def test_file_change_clears_trace(self, tmp_path: Path):
        kpi_path = write_correlated_kpi_xlsx(
            tmp_path / "weekly.xlsx",
            TEST_REGION,
            CONTROL_REGIONS,
            metric_name="Sales",
            n_periods=60,
            freq="W",
            seed=123,
        )
        app = _new_app()
        _manual_match(app)
        seed_plan_step(app, PlanStep.CHECK_DESIGN)
        app.run(timeout=RUN_TIMEOUT)
        _upload_kpi(app, "design", "weekly.xlsx", kpi_path.read_bytes())
        _inject_bayesian_state(app)
        # Uploading a new file fires clear_uploaded_kpi_state.
        _upload_kpi(app, "design", "weekly2.xlsx", kpi_path.read_bytes())
        _assert_trace_cleared(app)
