#!/usr/bin/env python3
"""Regenerate the power-methodology evidence v2 report (Stage 5).

Usage:
    python scripts/generate_evidence_v2.py

Writes two artifacts:

- ``docs/spikes/evidence/power-methodology-evidence-v2.json`` -- the full
  multi-seed run report (per-run records, additional safety-scenario table,
  aggregate summary). Includes per-run wall-clock runtime, so this artifact
  is NOT byte-reproducible run to run; there is no CI consistency check for
  it (unlike the v1 report). It runs the candidate power method across
  multiple independent data-generation seeds x simulation seeds using the
  scenarios in ``geotestlab.power.market_evidence`` plus the additional
  safety-scenario suite in ``geotestlab.power.evidence_v2``.
- ``docs/spikes/evidence/power-methodology-evidence-v2-summary.json`` -- the
  concise machine-readable summary (methodology version, scenario-suite
  version, generating commit SHA, settings, PROPOSED acceptance thresholds,
  summary metrics, blocked scenarios, open decisions).

This script NEVER runs in CI; a maintainer reviews the evidence before
committing (a changed report is deliberate evidence, same convention as
``scripts/update_market_evidence.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2.json"
SUMMARY_PATH = (
    REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2-summary.json"
)

sys.path.insert(0, str(REPO_ROOT))

from geotestlab.power.evidence_v2 import (  # noqa: E402
    build_concise_summary,
    run_evidence_v2,
)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-sim",
        type=int,
        default=None,
        help="override the per-run simulation count (default: evidence_v2.DEFAULT_N_SIM)",
    )
    args = parser.parse_args(argv)

    kwargs = {}
    if args.n_sim is not None:
        kwargs["n_sim"] = args.n_sim

    report = run_evidence_v2(**kwargs)
    summary = build_concise_summary(report)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"evidence v2 report written: {REPORT_PATH}")
    print(f"evidence v2 summary written: {SUMMARY_PATH}")
    print(f"total runs: {report['summary']['total_runs']}")
    print(f"n completed: {report['summary']['n_completed']}")
    print(
        f"safety-scenario pass rate: {report['summary']['additional_safety_scenarios']['pass_rate']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
