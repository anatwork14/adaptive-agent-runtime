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

    The repository is the only host path mounted into the container. Network is
    disabled by default, capabilities are dropped, privilege escalation is
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
        image_digest: Optional[str] = None,
        tmpfs_noexec: bool = True,
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.network_enabled = network_enabled
        self.timeout_seconds = timeout_seconds
        self.image = image or os.environ.get("ARC_SANDBOX_IMAGE", "arc-runner:latest")
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit
        self.image_digest = image_digest
        self.tmpfs_noexec = tmpfs_noexec

    def _inspect_image(self, docker: str) -> str:
        inspect = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", self.image],
            capture_output=True,
            text=True,
        )
        actual_digest = inspect.stdout.strip()
        if inspect.returncode != 0 or not actual_digest:
            detail = (inspect.stderr or inspect.stdout or "image inspection failed").strip()
            raise SandboxUnavailable(f"sandbox image '{self.image}' cannot be inspected: {detail}")
        return actual_digest

    def _docker(self) -> str:
        docker = shutil.which("docker")
        if docker is None:
            raise SandboxUnavailable(
                "Docker is required for ARC sandboxed execution. "
                "Install Docker or configure a compatible execution backend; "
                "ARC will not silently fall back to host subprocess execution."
            )
        actual_digest = self._inspect_image(docker)
        if self.image_digest and actual_digest != self.image_digest:
            raise SandboxUnavailable(
                f"sandbox image identity mismatch for '{self.image}': "
                f"expected={self.image_digest}, actual={actual_digest}"
            )
        return docker

    def verify_available(self) -> dict[str, object]:
        """Passively verify Docker and the frozen image identity.

        This method performs only executable/daemon/image inspection. It never
        starts a container, so callers can use it during a read-only campaign
        preflight without beginning benchmark execution.
        """
        docker = shutil.which("docker")
        if docker is None:
            raise SandboxUnavailable(
                "Docker executable is unavailable; the frozen sandbox cannot be verified"
            )

        daemon = subprocess.run(
            [docker, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
        )
        if daemon.returncode != 0:
            detail = (daemon.stderr or daemon.stdout or "Docker daemon is unavailable").strip()
            raise SandboxUnavailable(f"Docker daemon is unavailable: {detail}")

        actual_docker = docker
        actual_digest = self._inspect_image(actual_docker)
        if self.image_digest and actual_digest != self.image_digest:
            raise SandboxUnavailable(
                f"sandbox image identity mismatch for '{self.image}': "
                f"expected={self.image_digest}, actual={actual_digest}"
            )
        return {
            "backend": "docker",
            "docker_executable": actual_docker,
            "daemon_ready": True,
            "image": self.image,
            "expected_image_digest": self.image_digest,
            "actual_image_digest": actual_digest,
            "ready": True,
        }

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
        read_only_mounts: Optional[Dict[str, str | Path]] = None,
        workspace_read_only: bool = False,
    ) -> ExecutionResult:
        """Execute ``command`` in a least-privilege Docker container.

        Hidden grading sets ``workspace_read_only`` so test imports and other
        grader activity cannot dirty the integrated candidate tree.
        """
        if not command:
            raise ValueError("sandbox command must not be empty")
        docker = self._docker()
        exec_cwd = (cwd or self.workspace_path).resolve()
        container_cwd = self._container_cwd(exec_cwd)

        tmpfs_options = "rw,exec,nosuid,size=256m"
        if self.tmpfs_noexec:
            tmpfs_options = "rw,noexec,nosuid,size=256m"
        docker_cmd: List[str] = [
            docker,
            "run",
            "--rm",
            "--init",
            "--workdir",
            container_cwd,
            "--mount",
            (
                f"type=bind,src={self.workspace_path},dst=/workspace"
                + (",readonly" if workspace_read_only else "")
            ),
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
            f"/tmp:{tmpfs_options}",
        ]
        if os.name == "posix" and hasattr(os, "getuid") and hasattr(os, "getgid"):
            docker_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        if not self.network_enabled:
            docker_cmd.extend(["--network", "none"])

        for target, source in sorted((read_only_mounts or {}).items()):
            source_path = Path(source).resolve()
            if not source_path.is_dir():
                raise SandboxUnavailable(f"read-only mount source does not exist: {source_path}")
            if not target.startswith("/") or target == "/workspace":
                raise SandboxUnavailable(f"invalid read-only mount target: {target}")
            docker_cmd.extend(
                [
                    "--mount",
                    f"type=bind,src={source_path},dst={target},readonly",
                ]
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
