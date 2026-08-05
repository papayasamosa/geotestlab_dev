"""Review-completeness merge gate (Stage 3).

Direct unit tests for the pure thread-evaluation logic in
``scripts/check_review_gate.py``: resolved, unresolved, outdated, P1, P2 and
lower-priority (P3+/no-marker) threads.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_review_gate import find_blocking_threads, has_p1_p2_marker  # noqa: E402


def _thread(thread_id="t1", is_resolved=False, is_outdated=False, bodies=("no marker",)):
    # comments uses the real GraphQL connection shape: {"nodes": [{"body": ...}]}
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "isOutdated": is_outdated,
        "comments": {"nodes": [{"body": b} for b in bodies]},
    }


class TestP1P2Marker:
    def test_p2_badge_marker(self):
        assert has_p1_p2_marker("**P2 Badge**  some finding")
        assert has_p1_p2_marker("![P2 Badge](https://img.shields.io/badge/P2-yellow)")
        assert has_p1_p2_marker("![P1 Badge](https://img.shields.io/badge/P1-red)")

    def test_standalone_p1_p2_tokens(self):
        assert has_p1_p2_marker("P1: something")
        assert has_p1_p2_marker("needs fixing (P2)")

    def test_no_marker(self):
        assert not has_p1_p2_marker("")
        assert not has_p1_p2_marker("Looks good, no issues.")
        assert not has_p1_p2_marker("P3 Badge")
        assert not has_p1_p2_marker("review P22 report")

    def test_not_substring_of_other_words(self):
        assert not has_p1_p2_marker("RP2 and XP1 are region codes")
        assert not has_p1_p2_marker("AP21")


class TestFindBlockingThreads:
    def test_resolved_p2_does_not_block(self):
        assert find_blocking_threads([_thread(is_resolved=True, bodies=("**P2 Badge** x",))]) == []

    def test_unresolved_p2_blocks(self):
        assert [t["id"] for t in find_blocking_threads([_thread(bodies=("**P2 Badge** x",))])] == [
            "t1"
        ]

    def test_outdated_p1_does_not_block(self):
        assert find_blocking_threads([_thread(is_outdated=True, bodies=("**P1 Badge** x",))]) == []

    def test_unresolved_p1_blocks(self):
        assert [t["id"] for t in find_blocking_threads([_thread(bodies=("**P1 Badge** x",))])] == [
            "t1"
        ]

    def test_lower_priority_does_not_block(self):
        assert find_blocking_threads([_thread(bodies=("**P3 Badge** x",))]) == []

    def test_no_marker_does_not_block(self):
        assert find_blocking_threads([_thread(bodies=("Just a nitpick.",))]) == []

    def test_empty_threads(self):
        assert find_blocking_threads([]) == []
        assert find_blocking_threads(None) == []

    def test_mixed_threads_only_blocks_p1_p2(self):
        threads = [
            _thread("t1", is_resolved=True, bodies=("**P2 Badge** x",)),  # resolved -> ok
            _thread("t2", is_outdated=True, bodies=("**P1 Badge** x",)),  # outdated -> ok
            _thread("t3", bodies=("**P2 Badge** y",)),  # BLOCK
            _thread("t4", bodies=("**P3 Badge** z",)),  # low priority -> ok
            _thread("t5", bodies=("no marker",)),  # ok
            _thread("t6", bodies=("**P1 Badge** a",)),  # BLOCK
        ]
        assert [t["id"] for t in find_blocking_threads(threads)] == ["t3", "t6"]

    def test_marker_in_later_comment_counts(self):
        threads = [_thread(bodies=("first", "**P2 Badge** found"))]
        assert [t["id"] for t in find_blocking_threads(threads)] == ["t1"]

    def test_thread_without_comments(self):
        threads = [{"id": "t1", "isResolved": False, "isOutdated": False, "comments": []}]
        assert find_blocking_threads(threads) == []

    def test_unresolved_p2_with_real_api_comments_shape_blocks(self):
        # Regression: the GraphQL comments connection returns {nodes: [...]};
        # iterating the dict directly crashed with "'str' object has no
        # attribute 'get'" (dict iteration yields the key 'nodes').
        thread = {
            "id": "t1",
            "isResolved": False,
            "isOutdated": False,
            "comments": {"nodes": [{"body": "**P2 Badge**  some finding"}]},
        }
        assert [t["id"] for t in find_blocking_threads([thread])] == ["t1"]

    def test_bare_list_comments_shape_tolerated(self):
        thread = {
            "id": "t1",
            "isResolved": False,
            "isOutdated": False,
            "comments": [{"body": "**P1 Badge**  x"}],
        }
        assert [t["id"] for t in find_blocking_threads([thread])] == ["t1"]


class TestMain:
    def test_main_fails_when_blocking_threads(self, monkeypatch, capsys):
        from check_review_gate import main

        def _fake_fetch(repo, pr, gh="gh"):
            return [
                {
                    "id": "t1",
                    "isResolved": False,
                    "isOutdated": False,
                    "comments": [{"body": "**P2 Badge**  some finding"}],
                }
            ]

        monkeypatch.setattr("check_review_gate.fetch_review_threads", _fake_fetch)
        assert main(["--repo", "o/r", "--pr", "1"]) == 1
        assert "FAIL" in capsys.readouterr().err

    def test_main_passes_when_no_blocking_threads(self, monkeypatch, capsys):
        from check_review_gate import main

        monkeypatch.setattr("check_review_gate.fetch_review_threads", lambda repo, pr, gh="gh": [])
        assert main(["--repo", "o/r", "--pr", "1"]) == 0
        assert "PASS" in capsys.readouterr().out

    def test_main_passes_when_only_resolved_or_outdated(self, monkeypatch, capsys):
        from check_review_gate import main

        def _fake_fetch(repo, pr, gh="gh"):
            return [
                {
                    "id": "a",
                    "isResolved": True,
                    "isOutdated": False,
                    "comments": [{"body": "**P1 Badge**  x"}],
                },
                {
                    "id": "b",
                    "isResolved": False,
                    "isOutdated": True,
                    "comments": [{"body": "**P2 Badge**  y"}],
                },
            ]

        monkeypatch.setattr("check_review_gate.fetch_review_threads", _fake_fetch)
        assert main(["--repo", "o/r", "--pr", "1"]) == 0
        assert "PASS" in capsys.readouterr().out


class TestPagination:
    def test_fetch_paginates_all_threads(self, monkeypatch):
        from check_review_gate import fetch_review_threads

        pages = [
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": True, "endCursor": "cursor2"},
                                "nodes": [
                                    {
                                        "id": "t1",
                                        "isResolved": False,
                                        "isOutdated": False,
                                        "comments": [],
                                    }
                                ],
                            }
                        }
                    }
                }
            },
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "t2",
                                        "isResolved": False,
                                        "isOutdated": False,
                                        "comments": [],
                                    }
                                ],
                            }
                        }
                    }
                }
            },
        ]
        calls = []

        def _fake_gh(query_json, gh):
            calls.append(query_json)
            return pages[len(calls) - 1]

        monkeypatch.setattr("check_review_gate._gh_graphql", _fake_gh)
        threads = fetch_review_threads("o/r", 1, gh="gh")
        assert [t["id"] for t in threads] == ["t1", "t2"]
        assert len(calls) == 2
        # the second page request carries the endCursor from the first page
        assert '"cursor": "cursor2"' in calls[1]

    def test_single_page_no_cursor(self, monkeypatch):
        from check_review_gate import fetch_review_threads

        calls = []

        def _fake_gh(query_json, gh):
            calls.append(query_json)
            return {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [
                                    {
                                        "id": "t1",
                                        "isResolved": False,
                                        "isOutdated": False,
                                        "comments": [],
                                    }
                                ],
                            }
                        }
                    }
                }
            }

        monkeypatch.setattr("check_review_gate._gh_graphql", _fake_gh)
        threads = fetch_review_threads("o/r", 1, gh="gh")
        assert [t["id"] for t in threads] == ["t1"]
        assert len(calls) == 1
        assert '"cursor": null' in calls[0]
