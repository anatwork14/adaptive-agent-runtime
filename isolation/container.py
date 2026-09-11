"""Execution sandbox / container runner for agent tasks."""

import os
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


class SandboxRunner:
    """Runs commands in an isolated subprocess/container environment."""

    def __init__(
        self,
        workspace_path: str | Path,
        network_enabled: bool = False,
        timeout_seconds: int = 120,
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.network_enabled = network_enabled
        self.timeout_seconds = timeout_seconds

    def run_command(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env_vars: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """Run a command inside the sandbox."""
        exec_cwd = cwd or self.workspace_path
        exec_env = os.environ.copy()

        # Security boundary: strip any host credentials / keys
        for key in list(exec_env.keys()):
            if "TOKEN" in key.upper() or "SECRET" in key.upper() or "KEY" in key.upper():
                # Allow python/path/system vars
                if key not in ("PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP"):
                    del exec_env[key]

        if env_vars:
            exec_env.update(env_vars)

        # In non-networked mode, inject dummy proxy or flag
        if not self.network_enabled:
            exec_env["NO_NETWORK"] = "1"
            exec_env["http_proxy"] = "http://127.0.0.1:0"
            exec_env["https_proxy"] = "http://127.0.0.1:0"

        timeout_sec = timeout or self.timeout_seconds
        start_time = time.perf_counter()

        try:
            proc = subprocess.run(
                command,
                cwd=str(exec_cwd),
                env=exec_env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                command=command,
                exit_code=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                duration_ms=duration_ms,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            stdout = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode() if e.stdout else "")
            stderr = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode() if e.stderr else "")
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout=stdout,
                stderr=stderr + f"\nCommand timed out after {timeout_sec}s",
                duration_ms=duration_ms,
                timed_out=True,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                timed_out=False,
            )
