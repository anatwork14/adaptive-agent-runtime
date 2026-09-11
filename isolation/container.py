"""Docker-backed execution sandbox for repository commands and test suites."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ExecutionResult:
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False


class SandboxUnavailable(RuntimeError):
    """Raised when ARC cannot establish the requested isolation boundary."""


class SandboxRunner:
    """Run commands in a hardened Docker container, fail-closed.

    The old implementation executed directly on the host and merely pointed
    HTTP proxy variables at localhost. That does not prevent raw sockets,
    arbitrary host-file reads, or subprocess access. This runner requires a
    real Docker boundary for sandboxed command execution.

    The target repository is mounted read/write at ``/workspace`` because test
    and build tools commonly create caches/artifacts. The host root filesystem,
    credentials, and sibling paths are not mounted. Network is disabled by
    default. For benchmark repositories with custom dependencies, supply a
    prebuilt per-instance image via ``image=`` or ``ARC_SANDBOX_IMAGE``.
    """

    def __init__(
        self,
        workspace_path: str | Path,
        network_enabled: bool = False,
        timeout_seconds: int = 120,
        image: Optional[str] = None,
        cpus: float = 2.0,
        memory: str = "4g",
        pids_limit: int = 256,
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.network_enabled = network_enabled
        self.timeout_seconds = timeout_seconds
        self.image = image or os.environ.get("ARC_SANDBOX_IMAGE", "arc-runner:latest")
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit

    def _docker(self) -> str:
        docker = shutil.which("docker")
        if docker is None:
            raise SandboxUnavailable(
                "Docker is required for ARC sandboxed execution. "
                "Install Docker or configure a compatible execution backend; "
                "ARC will not silently fall back to host subprocess execution."
            )
        inspect = subprocess.run(
            [docker, "image", "inspect", self.image],
            capture_output=True,
            text=True,
        )
        if inspect.returncode != 0:
            raise SandboxUnavailable(
                f"sandbox image '{self.image}' is unavailable. Build the ARC image with "
                "`docker build -f Dockerfile.runner -t arc-runner:latest .` or set "
                "ARC_SANDBOX_IMAGE to a prebuilt benchmark image."
            )
        return docker

    def _container_cwd(self, cwd: Path) -> str:
        resolved = cwd.resolve()
        try:
            relative = resolved.relative_to(self.workspace_path)
        except ValueError as exc:
            raise SandboxUnavailable(
                f"sandbox cwd {resolved} escapes workspace {self.workspace_path}"
            ) from exc
        return "/workspace" if str(relative) == "." else f"/workspace/{relative.as_posix()}"

    def run_command(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """Execute ``command`` in a least-privilege Docker container."""
        if not command:
            raise ValueError("sandbox command must not be empty")
        docker = self._docker()
        exec_cwd = (cwd or self.workspace_path).resolve()
        container_cwd = self._container_cwd(exec_cwd)

        docker_cmd: List[str] = [
            docker,
            "run",
            "--rm",
            "--init",
            "--workdir",
            container_cwd,
            "--mount",
            f"type=bind,src={self.workspace_path},dst=/workspace",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--cpus",
            str(self.cpus),
            "--memory",
            self.memory,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
        ]
        if not self.network_enabled:
            docker_cmd.extend(["--network", "none"])

        # Do not inherit the host environment. Only explicit, non-secret values
        # supplied by the caller are forwarded.
        for key, value in sorted((env_vars or {}).items()):
            upper = key.upper()
            if any(marker in upper for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")):
                raise SandboxUnavailable(f"refusing to forward secret-like env var: {key}")
            docker_cmd.extend(["--env", f"{key}={value}"])

        docker_cmd.append(self.image)
        docker_cmd.extend(command)

        timeout_sec = timeout or self.timeout_seconds
        start = time.perf_counter()
        try:
            process = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return ExecutionResult(
                command=command,
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
                duration_ms=(time.perf_counter() - start) * 1000.0,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode() if exc.stdout else "")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode() if exc.stderr else "")
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\nSandbox command timed out after {timeout_sec}s",
                duration_ms=(time.perf_counter() - start) * 1000.0,
                timed_out=True,
            )
