"""Adversarial and regression test suite runner."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from isolation.container import ExecutionResult, SandboxRunner


@dataclass
class AdversarialTestResult:
    passed: bool
    total_tests: int
    failed_tests: int
    output: str


class AdversarialTestRunner:
    """Runs test suites or adversarial test scenarios against a workspace."""

    def __init__(
        self, workspace_path: str | Path, harness: Optional[dict[str, Any]] = None
    ) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.harness = dict(harness or {})
        self.sandbox = SandboxRunner(
            self.workspace_path,
            network_enabled=bool(self.harness.get("network_enabled", False)),
            timeout_seconds=int(self.harness.get("timeout_seconds", 120)),
            image=self.harness.get("image"),
            image_digest=self.harness.get("image_digest"),
            tmpfs_noexec=not bool(self.harness.get("tmpfs_exec", False)),
        )

    def run_tests(self, test_command: Optional[List[str]] = None) -> AdversarialTestResult:
        cmd = (
            test_command
            or list(self.harness.get("command", []))
            or [
                "python",
                "-m",
                "pytest",
                "-v",
            ]
        )
        result: ExecutionResult = self.sandbox.run_command(
            cmd,
            env_vars=dict(self.harness.get("environment", {})),
            timeout=int(self.harness.get("timeout_seconds", 120)),
        )

        passed = result.exit_code == 0
        output = result.stdout + "\n" + result.stderr
        failed_count = 0
        if not passed:
            failed_count = 1

        return AdversarialTestResult(
            passed=passed,
            total_tests=1,
            failed_tests=failed_count,
            output=output,
        )

    def run_hidden_tests(
        self,
        hidden_test_dir: str | Path,
        hidden_command: Optional[List[str]] = None,
    ) -> AdversarialTestResult:
        """Run hidden tests with the candidate and hidden suite on separate mounts."""
        hidden = Path(hidden_test_dir).resolve()
        cmd = hidden_command or list(self.harness.get("hidden_command", []))
        if not cmd:
            cmd = ["python", "-m", "pytest", "-q", "/arc-hidden-tests"]
        result = self.sandbox.run_command(
            cmd,
            env_vars=dict(self.harness.get("hidden_environment", {})),
            timeout=int(
                self.harness.get("hidden_timeout_seconds", self.harness.get("timeout_seconds", 120))
            ),
            read_only_mounts={"/arc-hidden-tests": hidden},
        )
        output = result.stdout + "\n" + result.stderr
        return AdversarialTestResult(
            passed=result.exit_code == 0,
            total_tests=1,
            failed_tests=0 if result.exit_code == 0 else 1,
            output=output,
        )
