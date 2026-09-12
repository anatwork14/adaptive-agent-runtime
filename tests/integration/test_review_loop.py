"""Integration coverage for ARC's persistent GitHub review loop."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from application.session_app import SessionArcApplication
from integrations.github_cli import GitHubCheck, GitHubFeedback, GitHubPullRequestSnapshot
from state.models import GateStatus, TaskStatus


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# review loop demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


class FakeGitHubClient:
    latest = GitHubPullRequestSnapshot(
        number=17,
        url="https://github.com/example/demo/pull/17",
        title="ARC T001",
        state="OPEN",
        head_ref="arc/task/T001",
        base_ref="main",
        review_decision="",
        merge_state_status="UNSTABLE",
        checks=[GitHubCheck(name="tests", status="IN_PROGRESS", conclusion="")],
        feedback=[],
        digest="initial",
    )
    publish_calls = 0
    update_calls = 0

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path)

    def doctor(self):
        return {"status": "READY", "detail": "fake GitHub ready"}

    def create_pr(self, **kwargs):
        type(self).publish_calls += 1
        return type(self).latest

    def update_pr(self, *args, **kwargs):
        type(self).update_calls += 1
        return type(self).latest

    def snapshot(self, pr):
        return type(self).latest


def test_review_feedback_returns_to_same_worker_and_committed_pr_candidate_submits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.setattr("application.reviews.GitHubCliClient", FakeGitHubClient)
    FakeGitHubClient.publish_calls = 0
    FakeGitHubClient.update_calls = 0
    FakeGitHubClient.latest = GitHubPullRequestSnapshot(
        number=17,
        url="https://github.com/example/demo/pull/17",
        title="ARC T001",
        state="OPEN",
        head_ref="arc/task/T001",
        base_ref="main",
        review_decision="",
        merge_state_status="UNSTABLE",
        checks=[GitHubCheck(name="tests", status="IN_PROGRESS", conclusion="")],
        feedback=[],
        digest="initial",
    )

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Implement a reviewable change")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        asyncio.run(arc.sessions.send(session.session_id, "Create the initial implementation"))

        linked = arc.reviews.publish(session.session_id, base="main")
        assert linked.linked
        assert linked.pr_number == 17
        assert FakeGitHubClient.publish_calls == 1
        assert not arc.sessions.changed_files(session.session_id)

        FakeGitHubClient.latest = GitHubPullRequestSnapshot(
            number=17,
            url="https://github.com/example/demo/pull/17",
            title="ARC T001",
            state="OPEN",
            head_ref="arc/task/T001",
            base_ref="main",
            review_decision="CHANGES_REQUESTED",
            merge_state_status="BLOCKED",
            checks=[GitHubCheck(name="tests", status="COMPLETED", conclusion="FAILURE")],
            feedback=[
                GitHubFeedback(
                    source="inline_review",
                    author="reviewer",
                    body="Preserve the lease fence while fixing the retry path.",
                    path="runtime/leases.py",
                    line=42,
                )
            ],
            digest="feedback-v1",
        )

        synced = asyncio.run(arc.reviews.sync(session.session_id, auto_apply=True))
        assert synced.changed
        assert synced.feedback_applied
        projected = arc.reviews.status(session.session_id)
        assert projected.applied_feedback_digest == "feedback-v1"
        assert projected.pending_feedback == ""

        refreshed = arc.sessions.get(session.session_id)
        assert refreshed is not None
        assert any("GitHub review update" in message.content for message in refreshed.messages)
        assert any(
            "Preserve the lease fence" in message.content and message.role == "user"
            for message in refreshed.messages
        )
        assert arc.sessions.changed_files(session.session_id)

        # Push the feedback fix. This commits the worker worktree again.
        arc.reviews.publish(session.session_id, base="main")
        assert FakeGitHubClient.update_calls == 1
        assert not arc.sessions.changed_files(session.session_id)

        # A clean worktree with worker-authored commits must still be a valid
        # exact candidate. A true no-op remains rejected by WorktreeManager.
        result = asyncio.run(arc.sessions.submit(session.session_id))
        assert result.status == GateStatus.ACCEPTED
        assert arc.get_task(task.task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]

        kinds = [event.kind for event in arc.task_events(task.task_id)]
        assert "session.pr_published" in kinds
        assert "session.pr_updated" in kinds
        assert "session.review_synced" in kinds
        assert "session.review_feedback" in kinds
        assert "session.review_feedback_applied" in kinds
        assert "gate.accepted" in kinds


def test_review_sync_is_digest_deduplicated(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.setattr("application.reviews.GitHubCliClient", FakeGitHubClient)
    FakeGitHubClient.publish_calls = 0
    FakeGitHubClient.update_calls = 0
    FakeGitHubClient.latest = GitHubPullRequestSnapshot(
        number=9,
        url="https://github.com/example/demo/pull/9",
        title="green",
        state="OPEN",
        head_ref="arc/task/T001",
        base_ref="main",
        review_decision="APPROVED",
        merge_state_status="CLEAN",
        checks=[GitHubCheck(name="tests", status="COMPLETED", conclusion="SUCCESS")],
        feedback=[],
        digest="green-v1",
    )

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Deduplicate external state")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        asyncio.run(arc.sessions.send(session.session_id, "Make the draft"))
        arc.reviews.publish(session.session_id)

        before = len(
            [event for event in arc.task_events(task.task_id) if event.kind == "session.review_synced"]
        )
        result = asyncio.run(arc.reviews.sync(session.session_id))
        after = len(
            [event for event in arc.task_events(task.task_id) if event.kind == "session.review_synced"]
        )
        assert not result.changed
        assert after == before
        assert result.status.healthy
