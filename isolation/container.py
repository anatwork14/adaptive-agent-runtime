"""Docker-backed execution sandbox for repository commands and test suites."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


WORKSPACE_PYTHONPATH = "/workspace/src:/workspace"


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

    The repository is the primary host path mounted into the container. Trusted
    evaluation assets may be attached through explicit read-only mounts. Network
    is disabled by default, capabilities are dropped, privilege escalation is
    disabled, and CPU/memory/PID limits are enforced. The container runs with
    the host uid/gid on POSIX so tools can create repository-local build/test
    artifacts without granting root ownership on the host.
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
                f"sandbox image '{self.image}' is unavailable. Build it with "
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

    @staticmethod
    def _validate_read_only_mount(source: str | Path, destination: str) -> tuple[Path, str]:
        src = Path(source).resolve()
        if not src.exists():
            raise SandboxUnavailable(f"read-only sandbox mount does not exist: {src}")
        if not destination.startswith("/") or destination == "/":
            raise SandboxUnavailable(
                f"read-only sandbox destination must be an absolute non-root path: {destination!r}"
            )
        if destination == "/workspace" or destination.startswith("/workspace/"):
            raise SandboxUnavailable(
                "read-only sandbox mounts cannot shadow the candidate /workspace tree"
            )
        if "," in destination:
            raise SandboxUnavailable("read-only sandbox destination cannot contain a comma")
        return src, destination

    def run_command(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        read_only_mounts: Optional[Dict[str | Path, str]] = None,
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
        if os.name == "posix" and hasattr(os, "getuid") and hasattr(os, "getgid"):
            docker_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        if not self.network_enabled:
            docker_cmd.extend(["--network", "none"])

        mounts = read_only_mounts or {}
        for source, destination in sorted(mounts.items(), key=lambda item: item[1]):
            src, dst = self._validate_read_only_mount(source, destination)
            docker_cmd.extend(
                ["--mount", f"type=bind,src={src},dst={dst},readonly"]
            )

        # Never inherit the host environment. Only explicit non-secret values
        # supplied by the caller are forwarded.
        for key, value in sorted((env_vars or {}).items()):
            upper = key.upper()
            if any(
                marker in upper
                for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "PRIVATE_KEY")
            ):
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
            stdout = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout.decode() if exc.stdout else "")
            )
            stderr = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr.decode() if exc.stderr else "")
            )
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\nSandbox command timed out after {timeout_sec}s",
                duration_ms=(time.perf_counter() - start) * 1000.0,
                timed_out=True,
            )
