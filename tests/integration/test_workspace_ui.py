"""Integration tests for the v0.6 session-centric ARC Workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from application.session_app import SessionArcApplication
from webui.workspace_server import create_workspace_app


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# workspace demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def test_workspace_serves_session_board_and_worker_lifecycle(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()

    app = create_workspace_app(repo=repo, project_id="demo")
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "ARC Workspace" in page.text
        assert "Agent workspace" in page.text

        snap = client.get("/api/snapshot")
        assert snap.status_code == 200
        assert snap.json()["sessions"] == []

        created = client.post(
            "/api/tasks",
            json={
                "goal": "Build workspace artifact",
                "files": [],
                "acceptance": ["integrates through ARC gate"],
                "risk": 0.2,
                "token_budget": 12000,
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]

        opened = client.post(f"/api/tasks/{task_id}/sessions", json={"agent": "mock"})
        assert opened.status_code == 201, opened.text
        session_id = opened.json()["session_id"]

        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["session"]["task_id"] == task_id
        assert detail.json()["terminal_command"] == f"arc attach {session_id}"

        turn = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": "Implement the supervised draft"},
        )
        assert turn.status_code == 200, turn.text
        assert any(msg["role"] == "assistant" for msg in turn.json()["messages"])

        files = client.get(f"/api/sessions/{session_id}/files")
        assert files.status_code == 200
        assert files.json()["files"]
        diff = client.get(f"/api/sessions/{session_id}/diff")
        assert diff.status_code == 200
        assert "instruction" in diff.json()["diff"]

        submitted = client.post(f"/api/sessions/{session_id}/submit", json={})
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "accepted"

        snap = client.get("/api/snapshot").json()
        final = next(session for session in snap["sessions"] if session["session_id"] == session_id)
        assert final["status"] == "accepted"
        task = next(task for task in snap["tasks"] if task["task_id"] == task_id)
        assert task["status"] == "completed"


def test_workspace_websocket_streams_authoritative_events(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()

    app = create_workspace_app(repo=repo, project_id="demo")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events?after=0") as websocket:
            event = websocket.receive_json()
            assert event["kind"] == "project.created"
            assert event["project_id"] == "demo"
