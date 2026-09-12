"""Unit coverage for GitHub review normalization."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from integrations.github_cli import GitHubCliClient


class FakeGitHubCli(GitHubCliClient):
    def __init__(self, repo_path: Path, pr_payload: dict, inline_payload: list[dict]) -> None:
        super().__init__(repo_path)
        self.pr_payload = pr_payload
        self.inline_payload = inline_payload

    def _gh(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["pr", "view"]:
            return subprocess.CompletedProcess(
                ["gh", *args],
                0,
                stdout=json.dumps(self.pr_payload),
                stderr="",
            )
        if args and args[0] == "api":
            return subprocess.CompletedProcess(
                ["gh", *args],
                0,
                stdout=json.dumps(self.inline_payload),
                stderr="",
            )
        raise AssertionError(f"unexpected gh call: {args}")

    def repo_slug(self) -> str:
        return "example/arc-demo"


def test_snapshot_normalizes_checks_reviews_comments_and_inline_feedback(tmp_path: Path) -> None:
    client = FakeGitHubCli(
        tmp_path,
        pr_payload={
            "number": 42,
            "url": "https://github.com/example/arc-demo/pull/42",
            "title": "ARC review",
            "state": "OPEN",
            "headRefName": "arc/task/T001",
            "baseRefName": "main",
            "reviewDecision": "CHANGES_REQUESTED",
            "mergeStateStatus": "BLOCKED",
            "statusCheckRollup": [
                {
                    "name": "tests",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://example.test/check/tests",
                },
                {
                    "name": "lint",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://example.test/check/lint",
                },
                {
                    "name": "package",
                    "status": "IN_PROGRESS",
                    "conclusion": "",
                    "detailsUrl": "https://example.test/check/package",
                },
            ],
            "reviews": [
                {
                    "author": {"login": "alice"},
                    "state": "CHANGES_REQUESTED",
                    "body": "Fix the race in the worker loop.",
                    "url": "https://example.test/review/1",
                }
            ],
            "comments": [
                {
                    "author": {"login": "bob"},
                    "body": "Please document the retry policy.",
                    "url": "https://example.test/comment/2",
                }
            ],
        },
        inline_payload=[
            {
                "user": {"login": "carol"},
                "body": "This branch needs to preserve the lease fence.",
                "html_url": "https://example.test/inline/3",
                "path": "runtime/leases.py",
                "line": 88,
            }
        ],
    )

    snapshot = client.snapshot(42)

    assert snapshot.number == 42
    assert snapshot.review_decision == "CHANGES_REQUESTED"
    assert [check.name for check in snapshot.failed_checks] == ["tests"]
    assert [check.name for check in snapshot.pending_checks] == ["package"]
    assert len(snapshot.feedback) == 3
    assert not snapshot.healthy
    text = snapshot.actionable_feedback()
    assert "tests: FAILURE" in text
    assert "alice" in text and "Fix the race" in text
    assert "runtime/leases.py:88" in text
    assert "lease fence" in text

    # Same normalized external state must produce the same replay/dedup digest.
    again = client.snapshot(42)
    assert again.digest == snapshot.digest


def test_successful_review_snapshot_is_healthy(tmp_path: Path) -> None:
    client = FakeGitHubCli(
        tmp_path,
        pr_payload={
            "number": 7,
            "url": "https://github.com/example/arc-demo/pull/7",
            "title": "green",
            "state": "OPEN",
            "headRefName": "arc/task/T007",
            "baseRefName": "main",
            "reviewDecision": "APPROVED",
            "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [
                {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ],
            "reviews": [],
            "comments": [],
        },
        inline_payload=[],
    )

    snapshot = client.snapshot(7)

    assert snapshot.healthy
    assert snapshot.actionable_feedback() == ""
