#!/usr/bin/env python3
"""Regenerate the power-methodology market-evidence report (Stage 4).

Usage:
    python scripts/update_market_evidence.py --approve   # write the report
    python scripts/update_market_evidence.py --check     # compare; exit 1 on mismatch

The report is a deterministic JSON artifact committed at
``docs/spikes/evidence/power-methodology-evidence.json``. It runs the three
candidate power methods (model simulation, residual simulation, placebo
empirical) x three counterfactual fit methods (OLS, Elastic Net, LASSO) across
the realistic market scenarios in ``geotestlab.power.market_evidence``, plus a
side matrix (positive / negative / two-sided) on the 104-week scenario.

The output is fully deterministic (fixed seeds; no timestamps or paths), so a
regenerated report must byte-match the committed one unless the methodology or
scenario definitions changed. This script NEVER runs in CI; the maintainer must
review the diff before committing (a changed report is deliberate evidence).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence.json"

sys.path.insert(0, str(REPO_ROOT))

from geotestlab.power.market_evidence import (  # noqa: E402
    MARKET_SCENARIOS,
    combine_evidence,
    run_market_evidence,
    strip_timing,
)

# Broad matrix: every scenario, method, fit method (positive side, 2 seeds).
BROAD_CONFIG = {
    "scenario_names": None,  # all MARKET_SCENARIOS
    "methods": ("model_simulation", "residual_simulation", "placebo_empirical"),
    "fit_methods": ("ols", "elastic_net", "lasso"),
    "sides": ("one_sided_positive",),
    "seeds": (0, 1),
    "n_sim": 500,
}

# Side matrix: 104-week scenario, all three sides, OLS fit (positive side is
# already covered by the broad matrix, so only the two extra sides run here).
SIDE_CONFIG = {
    "scenario_names": ("weekly_104",),
    "methods": ("model_simulation", "residual_simulation", "placebo_empirical"),
    "fit_methods": ("ols",),
    "sides": ("one_sided_negative", "two_sided"),
    "seeds": (0, 1),
    "n_sim": 500,
}


def generate_full_report() -> dict:
    """Run the full evidence matrix and return the combined report dict with
    runtime stripped (runtime is non-deterministic; it is reported separately
    in the methodology document)."""
    broad = run_market_evidence(**BROAD_CONFIG)
    side = run_market_evidence(**SIDE_CONFIG)
    report = combine_evidence(broad, side)
    report["scenario_names"] = list(MARKET_SCENARIOS)
    return strip_timing(report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve", action="store_true", help="write the report")
    parser.add_argument("--check", action="store_true", help="compare and exit 1 on mismatch")
    parser.add_argument("--out", type=Path, default=None, help="override output path")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else REPORT_PATH
    report = generate_full_report()
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"

    if args.approve:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(out)
        print(f"market evidence report written: {out} ({len(payload)} bytes)")
        return 0

    if args.check:
        if not out.exists():
            print(f"market evidence report missing: {out} (run --approve)")
            return 1
        current = out.read_text(encoding="utf-8")
        if current == payload:
            print(f"market evidence report up to date: {out}")
            return 0
        print(f"market evidence report OUT OF DATE: {out}")
        print("Regenerate with: python scripts/update_market_evidence.py --approve")
        return 1

    parser.error("pass --approve or --check")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
