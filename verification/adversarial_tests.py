"""Adversarial and regression test suite runner."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from isolation.container import ExecutionResult, SandboxRunner


@dataclass
class AdversarialTestResult:
    passed: bool
    total_tests: int
    failed_tests: int
    output: str


class AdversarialTestRunner:
    """Runs test suites or adversarial test scenarios against a workspace."""

    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace_path = Path(workspace_path).resolve()
        self.sandbox = SandboxRunner(self.workspace_path)

    def run_tests(self, test_command: Optional[List[str]] = None) -> AdversarialTestResult:
        cmd = test_command or ["python", "-m", "pytest", "-v"]
        result: ExecutionResult = self.sandbox.run_command(cmd)

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
