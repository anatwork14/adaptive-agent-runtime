"""Persistent live-runtime supervision for ARC worker sessions.

The event log records how ARC asked an external runtime backend to start/stop a
terminal or preview, while tmux owns the actual long-lived PTY/process. Live
process state is therefore operational and recoverable, never authoritative
project truth.
"""

from __future__ import annotations

import shlex
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from runtime.tmux import TmuxController

if TYPE_CHECKING:  # pragma: no cover
    from application.app import ArcApplication


RuntimeKind = Literal["terminal", "preview"]


class WorkerRuntimeState(BaseModel):
    session_id: str
    kind: RuntimeKind
    backend: str = "tmux"
    runtime_name: str = ""
    command: list[str] = Field(default_factory=list)
    workspace: str = ""
    running: bool = False
    started_event: int | None = None
    stopped_event: int | None = None
    host: str = ""
    port: int | None = None
    url: str = ""
    ready: bool = False
    log_tail: str = ""


class WorkerRuntimeManager:
    """Manage tmux-backed provider terminals and localhost preview servers."""

    def __init__(self, app: "ArcApplication", tmux: TmuxController | None = None) -> None:
        self.app = app
        self.tmux = tmux or TmuxController()

    def doctor(self) -> dict[str, Any]:
        return self.tmux.doctor()

    def _session(self, session_id: str, *, require_workspace: bool = True):
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        workspace = Path(session.worktree_path)
        if require_workspace and not workspace.exists():
            raise RuntimeError(f"Worker workspace is missing: {workspace}")
        return session, workspace

    def _require_active_session(self, session_id: str):
        session, workspace = self._session(session_id)
        if session.status not in self.app.sessions.ACTIVE:
            raise ValueError(
                f"Session {session_id} is {session.status.value}; live runtimes require an active worker"
            )
        return session, workspace

    def _events(self, session_id: str, kind: RuntimeKind) -> list[Any]:
        result = []
        for event in self.app.event_store.read_all(project_id=self.app.project_id):
            if event.task_id is None:
                continue
            if (event.payload.get("session_id") or event.correlation_id) != session_id:
                continue
            if event.kind not in {"session.runtime_started", "session.runtime_stopped"}:
                continue
            if event.payload.get("runtime_kind") != kind:
                continue
            result.append(event)
        return result

    @staticmethod
    def _redact_command(command: list[str]) -> list[str]:
        """Redact obvious secret-valued argv before writing an event."""
        secret_markers = ("token", "secret", "password", "passwd", "api-key", "apikey")
        output: list[str] = []
        redact_next = False
        for arg in command:
            lower = arg.lower()
            if redact_next:
                output.append("<redacted>")
                redact_next = False
                continue
            if any(marker in lower for marker in secret_markers):
                if "=" in arg:
                    output.append(arg.split("=", 1)[0] + "=<redacted>")
                else:
                    output.append(arg)
                    redact_next = True
                continue
            output.append(arg)
        return output

    def status(self, session_id: str, kind: RuntimeKind) -> WorkerRuntimeState:
        # Status remains inspectable after an accepted/stopped session has had
        # its draft worktree removed. ARC reconstructs metadata from events and
        # consults tmux only when an unmatched runtime-start event exists.
        _, workspace = self._session(session_id, require_workspace=False)
        state = WorkerRuntimeState(
            session_id=session_id,
            kind=kind,
            runtime_name=TmuxController.safe_name(kind, session_id),
            workspace=str(workspace),
        )
        for event in self._events(session_id, kind):
            payload = event.payload
            if event.kind == "session.runtime_started":
                state.backend = str(payload.get("backend") or "tmux")
                state.runtime_name = str(payload.get("runtime_name") or state.runtime_name)
                state.command = [str(item) for item in payload.get("command", [])]
                state.workspace = str(payload.get("workspace") or workspace)
                state.host = str(payload.get("host") or "")
                state.port = int(payload["port"]) if payload.get("port") is not None else None
                state.url = str(payload.get("url") or "")
                state.started_event = event.id
                state.stopped_event = None
            elif event.kind == "session.runtime_stopped":
                state.stopped_event = event.id
        state.running = bool(
            state.started_event
            and not state.stopped_event
            and self.tmux.has_session(state.runtime_name)
        )
        if state.running:
            state.log_tail = self.tmux.capture(state.runtime_name, lines=120)
        if kind == "preview" and state.running and state.port:
            state.ready = self._port_ready(state.host or "127.0.0.1", state.port)
        else:
            state.ready = state.running
        return state

    def _emit_started(
        self,
        *,
        session_id: str,
        kind: RuntimeKind,
        runtime_name: str,
        command: list[str],
        workspace: Path,
        host: str = "",
        port: int | None = None,
        url: str = "",
    ) -> None:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        self.app.event_store.append(
            actor="runtime-supervisor",
            kind="session.runtime_started",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "runtime_kind": kind,
                "backend": "tmux",
                "runtime_name": runtime_name,
                "command": self._redact_command(command),
                "workspace": str(workspace),
                "host": host,
                "port": port,
                "url": url,
            },
        )

    def _emit_stopped(self, session_id: str, kind: RuntimeKind, runtime_name: str) -> None:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        self.app.event_store.append(
            actor="runtime-supervisor",
            kind="session.runtime_stopped",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "runtime_kind": kind,
                "backend": "tmux",
                "runtime_name": runtime_name,
            },
        )

    def start_terminal(self, session_id: str) -> WorkerRuntimeState:
        _, workspace = self._require_active_session(session_id)
        current = self.status(session_id, "terminal")
        if current.running:
            return current
        command = self.app.sessions.native_command(session_id)
        name = TmuxController.safe_name("terminal", session_id)
        self.tmux.start(name=name, cwd=workspace, command=command)
        self._emit_started(
            session_id=session_id,
            kind="terminal",
            runtime_name=name,
            command=command,
            workspace=workspace,
        )
        return self.status(session_id, "terminal")

    def attach_terminal(self, session_id: str) -> int:
        state = self.start_terminal(session_id)
        session = self.app.sessions.get(session_id)
        assert session is not None
        self.app.event_store.append(
            actor="operator",
            kind="session.terminal_attached",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "backend": "tmux",
                "runtime_name": state.runtime_name,
            },
        )
        return self.tmux.attach(state.runtime_name)

    def stop_terminal(self, session_id: str) -> WorkerRuntimeState:
        current = self.status(session_id, "terminal")
        if current.running:
            self.tmux.stop(current.runtime_name)
            self._emit_stopped(session_id, "terminal", current.runtime_name)
        return self.status(session_id, "terminal")

    @staticmethod
    def _port_ready(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            return False

    @staticmethod
    def _port_available(host: str, port: int) -> bool:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def start_preview(
        self,
        session_id: str,
        *,
        command_template: str,
        port: int,
        host: str = "127.0.0.1",
    ) -> WorkerRuntimeState:
        _, workspace = self._require_active_session(session_id)
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("ARC previews are loopback-only")
        if not 1 <= port <= 65535:
            raise ValueError("Preview port must be between 1 and 65535")
        if not command_template.strip():
            raise ValueError("Preview command cannot be empty")
        if "{host}" not in command_template or "{port}" not in command_template:
            raise ValueError(
                "Preview command must include both {host} and {port} placeholders so ARC can enforce the loopback endpoint"
            )
        current = self.status(session_id, "preview")
        if current.running:
            raise RuntimeError(
                f"Preview is already running at {current.url or current.runtime_name}; stop it first"
            )
        if not self._port_available(host, port):
            raise RuntimeError(f"Preview port {host}:{port} is already in use")
        rendered = command_template.replace("{host}", host).replace("{port}", str(port))
        command = shlex.split(rendered)
        if not command:
            raise ValueError("Preview command did not produce an executable argv")
        name = TmuxController.safe_name("preview", session_id)
        self.tmux.start(name=name, cwd=workspace, command=command)
        if host == "localhost":
            url_host = "127.0.0.1"
        elif host == "::1":
            url_host = "[::1]"
        else:
            url_host = host
        url = f"http://{url_host}:{port}/"
        self._emit_started(
            session_id=session_id,
            kind="preview",
            runtime_name=name,
            command=command,
            workspace=workspace,
            host=host,
            port=port,
            url=url,
        )
        return self.status(session_id, "preview")

    def stop_preview(self, session_id: str) -> WorkerRuntimeState:
        current = self.status(session_id, "preview")
        if current.running:
            self.tmux.stop(current.runtime_name)
            self._emit_stopped(session_id, "preview", current.runtime_name)
        return self.status(session_id, "preview")
