"""Workspace API coverage for ARC's GitHub review control loop."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from application.session_app import SessionArcApplication
from integrations.github_cli import GitHubCheck, GitHubFeedback, GitHubPullRequestSnapshot
from webui.workspace_server import create_workspace_app


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# workspace review demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


class FakeGitHubClient:
    latest = GitHubPullRequestSnapshot(
        number=31,
        url="https://github.com/example/demo/pull/31",
        title="workspace review",
        state="OPEN",
        head_ref="arc/task/T001",
        base_ref="main",
        review_decision="",
        merge_state_status="UNSTABLE",
        checks=[GitHubCheck(name="tests", status="IN_PROGRESS", conclusion="")],
        feedback=[],
        digest="workspace-initial",
    )

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path)

    def doctor(self):
        return {"status": "READY", "detail": "fake GitHub ready"}

    def create_pr(self, **kwargs):
        return type(self).latest

    def update_pr(self, *args, **kwargs):
        return type(self).latest

    def snapshot(self, pr):
        return type(self).latest


def test_workspace_review_publish_sync_and_apply(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.setattr("application.reviews.GitHubCliClient", FakeGitHubClient)
    FakeGitHubClient.latest = GitHubPullRequestSnapshot(
        number=31,
        url="https://github.com/example/demo/pull/31",
        title="workspace review",
        state="OPEN",
        head_ref="arc/task/T001",
        base_ref="main",
        review_decision="",
        merge_state_status="UNSTABLE",
        checks=[GitHubCheck(name="tests", status="IN_PROGRESS", conclusion="")],
        feedback=[],
        digest="workspace-initial",
    )

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()

    app = create_workspace_app(repo=repo, project_id="demo")
    with TestClient(app) as client:
        created = client.post(
            "/api/tasks",
            json={
                "goal": "Build a reviewable workspace change",
                "files": [],
                "acceptance": ["review feedback can return to the worker"],
                "risk": 0.2,
                "token_budget": 12000,
            },
        )
        task_id = created.json()["task_id"]
        opened = client.post(f"/api/tasks/{task_id}/sessions", json={"agent": "mock"})
        session_id = opened.json()["session_id"]
        turn = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": "Create the first review draft"},
        )
        assert turn.status_code == 200, turn.text

        doctor = client.get("/api/reviews/doctor")
        assert doctor.status_code == 200
        assert doctor.json()["status"] == "READY"

        published = client.post(
            f"/api/reviews/{session_id}/publish",
            json={"base": "main", "remote": "origin", "title": None},
        )
        assert published.status_code == 200, published.text
        assert published.json()["pr_number"] == 31
        assert published.json()["linked"] is True

        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["review"]["pr_number"] == 31

        FakeGitHubClient.latest = GitHubPullRequestSnapshot(
            number=31,
            url="https://github.com/example/demo/pull/31",
            title="workspace review",
            state="OPEN",
            head_ref="arc/task/T001",
            base_ref="main",
            review_decision="CHANGES_REQUESTED",
            merge_state_status="BLOCKED",
            checks=[GitHubCheck(name="tests", status="COMPLETED", conclusion="FAILURE")],
            feedback=[
                GitHubFeedback(
                    source="review",
                    author="reviewer",
                    body="Fix the retry behavior and keep the existing acceptance criterion.",
                    state="CHANGES_REQUESTED",
                )
            ],
            digest="workspace-feedback-v1",
        )

        synced = client.post(f"/api/reviews/{session_id}/sync", json={"apply": False})
        assert synced.status_code == 200, synced.text
        assert synced.json()["changed"] is True
        assert "Fix the retry behavior" in synced.json()["status"]["pending_feedback"]

        applied = client.post(f"/api/reviews/{session_id}/apply", json={})
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] is True
        assert applied.json()["review"]["pending_feedback"] == ""

        detail = client.get(f"/api/sessions/{session_id}").json()
        assert any(
            message["role"] == "user" and "Fix the retry behavior" in message["content"]
            for message in detail["session"]["messages"]
        )
