"""Isolated Hidden Test Grader enforcing Invariant I10."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from isolation.container import SandboxRunner, WORKSPACE_PYTHONPATH


@dataclass
class GradingResult:
    passed: bool
    total_hidden_tests: int
    passed_hidden_tests: int
    regression_detected: bool
    output: str


class HiddenTestGrader:
    """Evaluates patches against hidden test suites in an isolated evaluation environment."""

    def __init__(self, hidden_test_dir: str | Path) -> None:
        self.hidden_test_dir = Path(hidden_test_dir).resolve()

    def grade(
        self,
        workspace_path: str | Path,
        test_file_pattern: str = "test_hidden_*.py",
    ) -> GradingResult:
        """Run hidden tests against the final integrated workspace."""
        ws_path = Path(workspace_path).resolve()
        hidden_files = sorted(self.hidden_test_dir.glob(test_file_pattern))

        if not hidden_files:
            return GradingResult(
                passed=True,
                total_hidden_tests=0,
                passed_hidden_tests=0,
                regression_detected=False,
                output="No hidden tests found for grading.",
            )

        # Hidden tests remain outside the candidate repository and are mounted
        # read-only only after provider work has finished. Candidate source is
        # forced ahead of site-packages so src-layout projects are graded against
        # the exact integrated tree rather than an installed package of the same
        # name.
        hidden_mount = "/arc-hidden-tests"
        cmd = ["python", "-m", "pytest", "-v"] + [
            f"{hidden_mount}/{path.name}" for path in hidden_files
        ]
        result = SandboxRunner(ws_path).run_command(
            cmd,
            env_vars={
                "PYTHONPATH": WORKSPACE_PYTHONPATH,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            read_only_mounts={self.hidden_test_dir: hidden_mount},
        )

        passed = result.exit_code == 0
        output = result.stdout + "\n" + result.stderr

        return GradingResult(
            passed=passed,
            total_hidden_tests=len(hidden_files),
            passed_hidden_tests=len(hidden_files) if passed else 0,
            regression_detected=not passed,
            output=output,
        )
