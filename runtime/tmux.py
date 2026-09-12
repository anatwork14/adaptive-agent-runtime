"""Optional tmux backend for persistent worker terminals and preview processes.

ARC does not implement its own terminal multiplexer. When tmux is available it
can delegate live PTY/process ownership to tmux while keeping only replayable
metadata in ARC events. This lets terminals survive the invoking ARC CLI process
without pretending an OS PID is durable project state.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class TmuxError(RuntimeError):
    """Raised when persistent tmux supervision is unavailable or fails."""


class TmuxController:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("tmux") or "tmux"

    def _run(
        self,
        args: list[str],
        *,
        check: bool = True,
        interactive: bool = False,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        command = [self.executable, *args]
        try:
            if interactive:
                result = subprocess.run(command, check=False)
            else:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                )
        except FileNotFoundError as exc:
            raise TmuxError("tmux is required for persistent terminal/preview supervision") from exc
        if check and result.returncode != 0:
            stderr = getattr(result, "stderr", None)
            stdout = getattr(result, "stdout", None)
            detail = str(stderr or stdout or "tmux command failed").strip()
            raise TmuxError(f"tmux {' '.join(args)} failed: {detail}")
        return result

    def doctor(self) -> dict[str, Any]:
        resolved = shutil.which(self.executable) if Path(self.executable).name == self.executable else self.executable
        if not resolved or not Path(resolved).exists():
            return {
                "status": "MISSING",
                "detail": "tmux is not installed; persistent PTY/preview mode is unavailable",
            }
        result = self._run(["-V"], check=False)
        if result.returncode != 0:
            return {"status": "ERROR", "detail": "tmux exists but could not report its version"}
        return {"status": "READY", "detail": str(result.stdout or "tmux").strip()}

    @staticmethod
    def safe_name(kind: str, session_id: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id)
        return f"arc-{kind}-{clean}"[:80]

    def has_session(self, name: str) -> bool:
        return self._run(["has-session", "-t", name], check=False).returncode == 0

    def start(
        self,
        *,
        name: str,
        cwd: str | Path,
        command: list[str],
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if not command:
            raise ValueError("Persistent runtime command cannot be empty")
        if self.has_session(name):
            raise TmuxError(f"tmux session {name!r} already exists")
        workspace = Path(cwd).resolve()
        if not workspace.exists():
            raise TmuxError(f"runtime working directory does not exist: {workspace}")

        # tmux accepts one shell-command string. When ARC supplies an explicit
        # environment, start through `env -i` so an existing tmux server cannot
        # silently reintroduce unrelated variables/secrets from its own process.
        runtime_command = list(command)
        if environment is not None:
            assignments = [f"{key}={environment[key]}" for key in sorted(environment)]
            runtime_command = ["env", "-i", *assignments, *runtime_command]

        shell_command = shlex.join(runtime_command)
        self._run(
            [
                "new-session",
                "-d",
                "-s",
                name,
                "-c",
                str(workspace),
                shell_command,
            ]
        )

    def attach(self, name: str) -> int:
        if not self.has_session(name):
            raise TmuxError(f"tmux session {name!r} is not running")
        return int(self._run(["attach-session", "-t", name], interactive=True).returncode)

    def stop(self, name: str) -> bool:
        if not self.has_session(name):
            return False
        self._run(["kill-session", "-t", name])
        return True

    def capture(self, name: str, *, lines: int = 120) -> str:
        if not self.has_session(name):
            return ""
        result = self._run(
            ["capture-pane", "-p", "-t", name, "-S", f"-{max(1, min(lines, 2000))}"],
            check=False,
        )
        return str(result.stdout or "")[-120000:]
