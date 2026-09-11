"""Integration coverage for the localhost ARC Web Mission Control."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from application.app import ArcApplication
from cli.entry import app as cli_app
from webui.server import create_web_app, run_web


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def test_web_api_drives_same_arc_application(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "web-demo") as arc:
        arc.initialize()

    client = TestClient(create_web_app(repo=repo, project_id="web-demo"))

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    created = client.post(
        "/api/tasks",
        json={
            "goal": "Create a Web Mission Control artifact",
            "files": ["web_demo.txt"],
            "acceptance": ["candidate integrates"],
            "risk": 0.2,
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task_id"]

    snapshot = client.get("/api/snapshot")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["project_id"] == "web-demo"
    assert any(task["task_id"] == task_id for task in body["tasks"])
    assert any(agent["name"] == "mock" for agent in body["agents"])

    context = client.get(f"/api/tasks/{task_id}/context?agent=mock")
    assert context.status_code == 200, context.text
    assert context.json()["task_id"] == task_id

    result = client.post(f"/api/tasks/{task_id}/run", json={"agent": "mock"})
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "accepted"
    assert (repo / "web_demo.txt").exists()

    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["task"]["status"] == "completed"
    assert any(event["kind"] == "gate.accepted" for event in detail.json()["events"])


def test_websocket_streams_authoritative_events(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "ws-demo") as arc:
        arc.initialize()
        arc.create_task("Visible over websocket", task_id="T001")

    client = TestClient(create_web_app(repo=repo, project_id="ws-demo"))
    with client.websocket_connect("/ws/events?after=0") as websocket:
        first = websocket.receive_json()
        second = websocket.receive_json()
    assert first["kind"] == "project.created"
    assert second["kind"] == "task.created"


def test_web_ui_is_served_and_arc_web_command_exists(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "ui-demo") as arc:
        arc.initialize()
    client = TestClient(create_web_app(repo=repo, project_id="ui-demo"))
    page = client.get("/")
    assert page.status_code == 200
    assert "ARC — Agent Orchestration Control" in page.text
    assert "Orchestrators" in page.text
    assert client.get("/static/mission.js").status_code == 200

    result = CliRunner().invoke(cli_app, ["web", "--help"])
    assert result.exit_code == 0, result.output
    assert "Mission Control" in result.output


def test_remote_binding_requires_explicit_opt_in(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with pytest.raises(ValueError, match="localhost-only"):
        run_web(repo=repo, host="0.0.0.0", port=8787, allow_remote=False)
