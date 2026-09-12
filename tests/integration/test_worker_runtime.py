"""Integration coverage for ARC's optional tmux-backed worker runtimes."""

from __future__ import annotations

import asyncio
import socket
import subprocess
from pathlib import Path

from application.session_app import SessionArcApplication
from state.models import GateStatus


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

    def start(self, *, name: str, cwd: str | Path, command: list[str]) -> None:
        if name in type(self).sessions:
            raise RuntimeError(f"duplicate fake tmux session: {name}")
        type(self).sessions[name] = {
            "cwd": str(Path(cwd).resolve()),
            "command": list(command),
            "log": f"started {' '.join(command)}",
        }

    def stop(self, name: str) -> bool:
        return type(self).sessions.pop(name, None) is not None

    def capture(self, name: str, *, lines: int = 120) -> str:
        row = type(self).sessions.get(name)
        return str(row["log"]) if row else ""

    def attach(self, name: str) -> int:
        if name not in type(self).sessions:
            raise RuntimeError("missing fake tmux session")
        return 0


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# runtime demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_preview_runtime_is_rediscovered_after_arc_restart(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    FakeTmux.sessions = {}
    monkeypatch.setattr("application.worker_runtime.TmuxController", FakeTmux)

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Run a persistent local preview")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        port = _free_port()
        preview = arc.worker_runtime.start_preview(
            session.session_id,
            command_template="python -m http.server {port} --bind {host}",
            port=port,
        )
        assert preview.running
        assert preview.url == f"http://127.0.0.1:{port}/"
        runtime_name = preview.runtime_name
        assert runtime_name in FakeTmux.sessions

    # Reconstructing SessionArcApplication must recover liveness from events +
    # the external tmux backend rather than a persisted PID/process handle.
    with SessionArcApplication(repo, "demo") as arc:
        recovered = arc.worker_runtime.status(session.session_id, "preview")
        assert recovered.running
        assert recovered.runtime_name == runtime_name
        assert recovered.started_event is not None
        stopped = arc.worker_runtime.stop_preview(session.session_id)
        assert not stopped.running
        assert runtime_name not in FakeTmux.sessions

        runtime_events = [
            event.kind
            for event in arc.task_events(task.task_id)
            if event.kind.startswith("session.runtime_")
        ]
        assert runtime_events == ["session.runtime_started", "session.runtime_stopped"]


def test_submit_stops_live_runtimes_before_worktree_cleanup(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    FakeTmux.sessions = {}
    monkeypatch.setattr("application.worker_runtime.TmuxController", FakeTmux)

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        # A command override lets the mock-backed worker exercise the provider
        # terminal runtime without requiring a real provider executable.
        arc.config.agents["mock"].command_override = "python -V"
        task = arc.create_task("Produce a candidate while live runtimes exist")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        asyncio.run(arc.sessions.send(session.session_id, "create the candidate"))
        workspace = Path(session.worktree_path)
        assert workspace.exists()

        terminal = arc.worker_runtime.start_terminal(session.session_id)
        preview = arc.worker_runtime.start_preview(
            session.session_id,
            command_template="python -m http.server {port} --bind {host}",
            port=_free_port(),
        )
        assert terminal.running and preview.running
        assert len(FakeTmux.sessions) == 2

        result = asyncio.run(arc.sessions.submit(session.session_id))
        assert result.status == GateStatus.ACCEPTED
        assert FakeTmux.sessions == {}
        assert not workspace.exists()

        events = arc.task_events(task.task_id)
        runtime_stops = [event.id for event in events if event.kind == "session.runtime_stopped"]
        accepted = next(event.id for event in events if event.kind == "session.accepted")
        assert runtime_stops
        assert max(runtime_stops) < accepted

        # Runtime inspection remains replayable even after accepted submission
        # removes the draft workspace. The historical metadata survives while
        # liveness correctly projects to stopped.
        terminal_after = arc.worker_runtime.status(session.session_id, "terminal")
        preview_after = arc.worker_runtime.status(session.session_id, "preview")
        assert not terminal_after.running
        assert not preview_after.running
        assert terminal_after.started_event is not None
        assert terminal_after.stopped_event is not None
        assert preview_after.started_event is not None
        assert preview_after.stopped_event is not None
        assert terminal_after.workspace == str(workspace)
        assert preview_after.workspace == str(workspace)


def test_preview_rejects_non_loopback_or_uncontrolled_bindings(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path)
    FakeTmux.sessions = {}
    monkeypatch.setattr("application.worker_runtime.TmuxController", FakeTmux)

    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Protect the preview boundary")
        session = arc.sessions.create(task.task_id, agent_name="mock")

        try:
            arc.worker_runtime.start_preview(
                session.session_id,
                command_template="python server.py --port {port} --host {host}",
                port=_free_port(),
                host="0.0.0.0",
            )
        except ValueError as exc:
            assert "loopback-only" in str(exc)
        else:  # pragma: no cover - safety regression sentinel
            raise AssertionError("non-loopback preview unexpectedly allowed")

        try:
            arc.worker_runtime.start_preview(
                session.session_id,
                command_template="python -m http.server 3000",
                port=_free_port(),
            )
        except ValueError as exc:
            assert "{host}" in str(exc) and "{port}" in str(exc)
        else:  # pragma: no cover - safety regression sentinel
            raise AssertionError("uncontrolled preview command unexpectedly allowed")
