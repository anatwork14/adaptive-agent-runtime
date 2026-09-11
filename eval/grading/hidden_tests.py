"""Isolated Hidden Test Grader enforcing Invariant I10."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


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
        hidden_files = list(self.hidden_test_dir.glob(test_file_pattern))

        if not hidden_files:
            return GradingResult(
                passed=True,
                total_hidden_tests=0,
                passed_hidden_tests=0,
                regression_detected=False,
                output="No hidden tests found for grading.",
            )

        # Run pytest specifically on the hidden test files against the workspace
        cmd = ["python", "-m", "pytest", "-v"] + [str(f) for f in hidden_files]
        proc = subprocess.run(
            cmd,
            cwd=str(ws_path),
            capture_output=True,
            text=True,
        )

        passed = proc.returncode == 0
        output = proc.stdout + "\n" + proc.stderr

        return GradingResult(
            passed=passed,
            total_hidden_tests=len(hidden_files),
            passed_hidden_tests=len(hidden_files) if passed else 0,
            regression_detected=not passed,
            output=output,
        )
