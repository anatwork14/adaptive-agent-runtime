"""Workspace API coverage for v0.8 persistent worker runtimes."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from application.session_app import SessionArcApplication
from webui.workspace_server import create_workspace_app


class FakeTmux:
    sessions: dict[str, dict] = {}

    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or "fake-tmux"

    @staticmethod
    def safe_name(kind: str, session_id: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)
        return f"arc-{kind}-{clean}"[:80]

    def doctor(self):
        return {"status": "READY", "detail": "fake tmux ready"}

    def has_session(self, name: str) -> bool:
        return name in type(self).sessions

    def start(
        self,
        *,
        name: str,
        cwd: str | Path,
        command: list[str],
        environment: dict[str, str] | None = None,
    ) -> None:
        type(self).sessions[name] = {
            "cwd": str(Path(cwd).resolve()),
            "command": list(command),
            "environment": dict(environment or {}),
            "log": "fake runtime output",
        }

    def stop(self, name: str) -> bool:
        return type(self).sessions.pop(name, None) is not None

    def capture(self, name: str, *, lines: int = 120) -> str:
        row = type(self).sessions.get(name)
        return str(row["log"]) if row else ""

    def attach(self, name: str) -> int:
        return 0


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# runtime api demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_workspace_runtime_api_start_status_stop(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    FakeTmux.sessions = {}
    monkeypatch.setattr("application.worker_runtime.TmuxController", FakeTmux)

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        # Persist the profile override because the Workspace intentionally opens
        # a fresh application instance for every request. The test therefore
        # exercises the same restart/config-reload boundary as the product.
        arc.config.agents["mock"].command_override = "python -V"
        arc.config_store.save(arc.config)
        task = arc.create_task("Expose runtime controls in Workspace")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        session_id = session.session_id

    app = create_workspace_app(repo=repo, project_id="demo")
    with TestClient(app) as client:
        doctor = client.get("/api/runtime/doctor")
        assert doctor.status_code == 200
        assert doctor.json()["status"] == "READY"

        initial = client.get(f"/api/sessions/{session_id}/runtime")
        assert initial.status_code == 200
        assert not initial.json()["terminal"]["running"]
        assert not initial.json()["preview"]["running"]

        terminal = client.post(f"/api/sessions/{session_id}/terminal/start", json={})
        assert terminal.status_code == 200, terminal.text
        assert terminal.json()["running"]

        port = _free_port()
        preview = client.post(
            f"/api/sessions/{session_id}/preview/start",
            json={
                "command": "python -m http.server {port} --bind {host}",
                "port": port,
                "host": "127.0.0.1",
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["running"]
        assert preview.json()["url"] == f"http://127.0.0.1:{port}/"

        status = client.get(f"/api/sessions/{session_id}/runtime").json()
        assert status["terminal"]["running"]
        assert status["preview"]["running"]
        assert status["preview"]["log_tail"] == "fake runtime output"

        stopped_preview = client.post(f"/api/sessions/{session_id}/preview/stop", json={})
        stopped_terminal = client.post(f"/api/sessions/{session_id}/terminal/stop", json={})
        assert stopped_preview.status_code == 200
        assert stopped_terminal.status_code == 200
        assert not stopped_preview.json()["running"]
        assert not stopped_terminal.json()["running"]
        assert FakeTmux.sessions == {}


def test_workspace_serves_runtime_preview_assets(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()

    app = create_workspace_app(repo=repo, project_id="demo")
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'data-tab="preview"' in page.text
        assert "/static/workspace-runtime.js" in page.text
        assert "/static/workspace-runtime.css" in page.text

        script = client.get("/static/workspace-runtime.js")
        stylesheet = client.get("/static/workspace-runtime.css")
        assert script.status_code == 200
        assert stylesheet.status_code == 200
        assert "preview/start" in script.text
        assert "preview-frame" in stylesheet.text
