#!/usr/bin/env python3
"""Review-completeness merge gate.

Fails (exit 1) when the target pull request has an UNRESOLVED, NON-OUTDATED
review thread carrying a P1 or P2 marker. Resolved threads, outdated threads
and lower-priority (P3+/no-marker) threads never block.

Can run in CI (GitHub Actions) or locally:

    python scripts/check_review_gate.py --repo owner/repo --pr 123

Uses the ``gh`` CLI's GraphQL API (auto-authenticated in Actions via
``GH_TOKEN``; locally it uses the user's ``gh`` auth).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# A "P1"/"P2" severity marker (e.g. Codex's "![P1 Badge]..." / "![P2 Badge]...").
_P1_P2_RE = re.compile(r"\bP[12]\b")


def has_p1_p2_marker(body: str) -> bool:
    """True when a thread comment body carries a P1 or P2 marker."""
    return bool(_P1_P2_RE.search(body or ""))


def find_blocking_threads(threads) -> list:
    """Threads that must block a merge: unresolved, not outdated, P1/P2 marker.

    ``threads`` is a list of dicts with keys ``isResolved``, ``isOutdated``,
    ``id`` and ``comments`` (a list of ``{"body": str}`` dicts). Pure and
    deterministic, so it is unit-tested directly.
    """
    blocking = []
    for thread in threads or []:
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        bodies = [c.get("body") or "" for c in thread.get("comments") or []]
        if any(has_p1_p2_marker(b) for b in bodies):
            blocking.append(thread)
    return blocking


def _graphql_query() -> str:
    return (
        "query($owner: String!, $name: String!, $number: Int!) { "
        "repository(owner: $owner, name: $name) { "
        "pullRequest(number: $number) { "
        "reviewThreads(first: 100) { nodes { id isResolved isOutdated "
        "comments(first: 100) { nodes { body } } } } } } }"
    )


def fetch_review_threads(repo: str, pr_number: int, gh: str = "gh") -> list:
    """Fetch the PR's review threads via ``gh api graphql``.

    The query + variables are passed through a temp JSON body so no shell
    quoting is involved (portable on Windows and Linux).
    """
    owner, name = repo.split("/", 1)
    query_json = json.dumps(
        {
            "query": _graphql_query(),
            "variables": {"owner": owner, "name": name, "number": int(pr_number)},
        }
    )
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(query_json)
            tmp_path = f.name
        proc = subprocess.run(
            [gh, "api", "graphql", "--input", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout)
        raise RuntimeError(f"gh api graphql failed (exit {proc.returncode})")
    data = json.loads(proc.stdout)
    nodes = (data.get("data") or {}).get("repository", {}).get("pullRequest", {}).get(
        "reviewThreads", {}
    ).get("nodes") or []
    return nodes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--gh", default=os.environ.get("GH", "gh"), help="gh executable")
    args = parser.parse_args(argv)

    threads = fetch_review_threads(args.repo, args.pr, gh=args.gh)
    blocking = find_blocking_threads(threads)
    if blocking:
        print(
            f"review-gate FAIL: {len(blocking)} unresolved, non-outdated review "
            f"thread(s) carry a P1/P2 marker on PR #{args.pr}:",
            file=sys.stderr,
        )
        for t in blocking:
            comments = t.get("comments") or []
            body = (comments[0].get("body") or "") if comments else ""
            first_line = body.strip().splitlines()[0] if body.strip() else "(no comment body)"
            print(f"  - thread {t.get('id')}: {first_line}", file=sys.stderr)
        return 1
    print(f"review-gate PASS: no blocking P1/P2 review threads on PR #{args.pr}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
