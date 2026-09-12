"""Integration coverage for ARC v0.10 supervised live provider turns."""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from application.config import AgentProfile
from application.session_app import SessionArcApplication
from state.models import TaskStatus
from webui.workspace_server import create_workspace_app


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# live turn demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


def _provider_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake_provider.py"
    script.write_text(
        "import sys,time\n"
        "sys.stdin.read()\n"
        "print('provider-ready', flush=True)\n"
        "print('provider-warning', file=sys.stderr, flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    return script


def _configure_live_worker(repo: Path, tmp_path: Path, project_id: str) -> tuple[str, Path]:
    script = _provider_script(tmp_path)
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    with SessionArcApplication(repo, project_id) as arc:
        arc.initialize()
        arc.add_agent(
            AgentProfile(
                name="live-test",
                provider="codex",
                command_override=command,
            )
        )
        task = arc.create_task("Exercise a supervised live provider turn")
        session = arc.sessions.create(task.task_id, agent_name="live-test")
        return session.session_id, Path(session.worktree_path)


def _wait_for_turn(client: TestClient, session_id: str, *, active: bool, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    latest: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/sessions/{session_id}/turn")
        assert response.status_code == 200, response.text
        latest = response.json()
        if bool(latest.get("active")) is active:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"turn did not reach active={active}: {latest}")


def _wait_for_event(client: TestClient, kind: str, *, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get("/api/events?after=0&limit=500")
        assert response.status_code == 200, response.text
        for event in response.json():
            if event["kind"] == kind:
                return event
        time.sleep(0.05)
    raise AssertionError(f"event {kind!r} was not observed")


def test_workspace_live_turn_starts_streams_and_cancels(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    session_id, worktree = _configure_live_worker(repo, tmp_path, "live-turn")
    assert worktree.exists()

    with TestClient(create_workspace_app(repo=repo, project_id="live-turn")) as client:
        started = client.post(
            f"/api/sessions/{session_id}/turn",
            json={"content": "work until I cancel"},
        )
        assert started.status_code == 202, started.text
        state = started.json()
        assert state["active"]
        assert state["turn_id"].startswith("TURN_")
        turn_id = state["turn_id"]

        output = _wait_for_event(client, "session.turn_output")
        assert output["payload"]["turn_id"] == turn_id
        assert output["payload"]["stream"] in {"stdout", "stderr"}

        # The same per-worker lock protects submit/review/runtime mutations while
        # a disposable provider process is editing the isolated worktree.
        blocked_submit = client.post(f"/api/sessions/{session_id}/submit", json={})
        assert blocked_submit.status_code == 409

        cancel = client.post(f"/api/sessions/{session_id}/turn/cancel", json={})
        assert cancel.status_code == 202, cancel.text
        assert cancel.json()["cancel_requested"]
        final_turn = _wait_for_turn(client, session_id, active=False)
        assert final_turn["turn_id"] == turn_id

        cancelled = _wait_for_event(client, "session.turn_cancelled")
        assert cancelled["payload"]["turn_id"] == turn_id
        detail = client.get(f"/api/sessions/{session_id}")
        assert detail.status_code == 200
        assert detail.json()["session"]["status"] == "open"
        kinds = [event["kind"] for event in detail.json()["events"]]
        assert "session.turn_started" in kinds
        assert "session.turn_output" in kinds
        assert "session.turn_cancel_requested" in kinds
        assert "session.turn_cancelled" in kinds


def test_workspace_stop_cancels_live_turn_before_worktree_removal(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    session_id, worktree = _configure_live_worker(repo, tmp_path, "stop-live-turn")

    with TestClient(create_workspace_app(repo=repo, project_id="stop-live-turn")) as client:
        started = client.post(
            f"/api/sessions/{session_id}/turn",
            json={"content": "keep editing"},
        )
        assert started.status_code == 202, started.text
        _wait_for_event(client, "session.turn_started")

        stopped = client.post(
            f"/api/sessions/{session_id}/stop",
            json={"reason": "operator closed supervised worker"},
        )
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "stopped"
        assert not worktree.exists()

        task_id = stopped.json()["task_id"]
        task = client.get(f"/api/tasks/{task_id}")
        assert task.status_code == 200
        assert task.json()["task"]["status"] == TaskStatus.READY.value
        kinds = [event["kind"] for event in task.json()["events"]]
        assert "session.turn_cancel_requested" in kinds
        assert "session.turn_cancelled" in kinds
        assert "session.stopped" in kinds
