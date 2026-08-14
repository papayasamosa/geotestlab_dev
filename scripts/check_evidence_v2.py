#!/usr/bin/env python3
"""Check the committed v2 methodology evidence for drift and unsafe status.

The full v2 study is deliberately maintainer-generated because it records
runtime and generation metadata.  CI still needs a deterministic signal that
the committed artefact describes the current code.  This checker runs a small
fixed sentinel suite and compares status-level decisions (not Monte-Carlo
point estimates) with the corresponding committed runs.  It also rejects an
artefact that reports a supported result for a scenario the safety policy says
must be blocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from geotestlab.power.evidence_v2 import (  # noqa: E402
    EVIDENCE_SUITE_VERSION,
    EXPECTED_BLOCKED_CORE_SCENARIOS,
    run_evidence_v2,
)

REPORT_PATH = REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2.json"
SUMMARY_PATH = (
    REPO_ROOT / "docs" / "spikes" / "evidence" / "power-methodology-evidence-v2-summary.json"
)

SENTINEL_SCENARIOS = ("weekly_104", "high_autocorrelation", "heteroskedastic")
SENTINEL_ADDITIONAL = ("duplicate_keys",)
SENTINEL_DATA_SEEDS = (0, 1, 2)
SENTINEL_SIM_SEEDS = (0, 1)


def _key(row: dict) -> tuple:
    return (
        row["scenario"],
        row["method"],
        row["fit_method"],
        int(row["data_seed"]),
        int(row["seed"]),
    )


def validate_artifact(report: dict, summary: dict) -> list[str]:
    errors: list[str] = []
    if report.get("evidence_suite_version") != EVIDENCE_SUITE_VERSION:
        errors.append(
            f"report suite version {report.get('evidence_suite_version')!r} "
            f"!= code version {EVIDENCE_SUITE_VERSION!r}"
        )
    if summary.get("scenario_suite_version") != EVIDENCE_SUITE_VERSION:
        errors.append("summary suite version does not match code")
    config = report.get("config", {})
    if len(config.get("data_seeds", ())) < 5:
        errors.append("v2 evidence must use at least five independent data-generation seeds")
    if len(config.get("sim_seeds", ())) < 3:
        errors.append("v2 evidence must use at least three independent simulation seeds")
    if not {"ols", "elastic_net", "lasso"} <= set(config.get("fit_methods", ())):
        errors.append("v2 evidence must include OLS, Elastic Net and LASSO paths")
    if summary.get("status", "").lower().find("not an approval") < 0:
        errors.append("v2 summary must remain explicitly non-approval evidence")

    rows = report.get("runs", [])
    scenario_results = summary.get("summary_metrics", {}).get("scenario_results", {})
    for scenario in EXPECTED_BLOCKED_CORE_SCENARIOS:
        supported = [r for r in rows if r.get("scenario") == scenario and r.get("completed")]
        flagged = [
            value
            for key, value in scenario_results.items()
            if key.startswith(f"{scenario}|") and value.get("false_supported")
        ]
        if supported and not flagged:
            errors.append(f"unsafe scenario {scenario!r} has unlabelled supported evidence runs")
    metrics = summary.get("summary_metrics", {})
    if "false_supported_rate" not in metrics or "false_blocked_rate" not in metrics:
        errors.append("summary must record both false-supported and false-blocked rates")
    safety = metrics.get("additional_safety_scenarios", {})
    if safety.get("n_scenarios", 0) == 0:
        errors.append("additional safety scenario evidence is missing")
    if not metrics.get("scenario_results"):
        errors.append("summary must contain scenario-level results")
    return errors


def compare_sentinel(report: dict, sentinel: dict) -> list[str]:
    committed = {_key(row): row for row in report.get("runs", [])}
    errors: list[str] = []
    for row in sentinel["runs"]:
        key = _key(row)
        actual = committed.get(key)
        if actual is None:
            errors.append(f"committed report is missing sentinel run {key}")
            continue
        for field in ("completed", "support_status", "fit_method_used"):
            if actual.get(field) != row.get(field):
                errors.append(
                    f"sentinel drift for {key}: {field} {actual.get(field)!r} != {row.get(field)!r}"
                )
    return errors


def main() -> int:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    errors = validate_artifact(report, summary)
    sentinel = run_evidence_v2(
        scenario_names=SENTINEL_SCENARIOS,
        additional_scenario_names=SENTINEL_ADDITIONAL,
        methods=("model_simulation",),
        fit_methods=("ols",),
        data_seeds=SENTINEL_DATA_SEEDS,
        sim_seeds=SENTINEL_SIM_SEEDS,
        n_sim=200,
    )
    errors.extend(compare_sentinel(report, sentinel))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("power evidence v2 artefact and deterministic sentinel are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
