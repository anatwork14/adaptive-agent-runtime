"""Isolated Hidden Test Grader enforcing Invariant I10."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from verification.adversarial_tests import AdversarialTestRunner


@dataclass
class GradingResult:
    passed: bool
    total_hidden_tests: int
    passed_hidden_tests: int
    regression_detected: bool
    output: str


class HiddenTestGrader:
    """Evaluates patches against hidden test suites in an isolated evaluation environment."""

    def __init__(
        self,
        hidden_test_dir: str | Path,
        *,
        harness: Optional[dict[str, Any]] = None,
        hidden_tests_required: bool | None = None,
    ) -> None:
        self.hidden_test_dir = Path(hidden_test_dir).resolve()
        self.harness = dict(harness or {})
        self.hidden_tests_required = (
            bool(hidden_tests_required) if hidden_tests_required is not None else True
        )

    def grade(
        self,
        workspace_path: str | Path,
        test_file_pattern: str = "test_hidden_*.py",
    ) -> GradingResult:
        """Run hidden tests against the final integrated workspace."""
        ws_path = Path(workspace_path).resolve()
        hidden_files = sorted(
            item for item in self.hidden_test_dir.glob(test_file_pattern) if item.is_file()
        )

        if not hidden_files:
            if self.hidden_tests_required:
                return GradingResult(
                    passed=False,
                    total_hidden_tests=0,
                    passed_hidden_tests=0,
                    regression_detected=True,
                    output=(
                        "No hidden tests matched required pattern "
                        f"{test_file_pattern!r}; refusing to grade an empty selection."
                    ),
                )
            return GradingResult(
                passed=True,
                total_hidden_tests=0,
                passed_hidden_tests=0,
                regression_detected=False,
                output="No hidden tests found for grading.",
            )

        basenames = [item.name for item in hidden_files]
        if len(set(basenames)) != len(basenames):
            return GradingResult(
                passed=False,
                total_hidden_tests=len(hidden_files),
                passed_hidden_tests=0,
                regression_detected=True,
                output="Hidden-test basename collision prevents safe container mapping.",
            )

        if not self.harness:
            return GradingResult(
                passed=False,
                total_hidden_tests=len(hidden_files),
                passed_hidden_tests=0,
                regression_detected=True,
                output=(
                    "A frozen repository-specific Docker harness is required for hidden grading; "
                    "host-Python fallback is disabled."
                ),
            )

        result = AdversarialTestRunner(ws_path, harness=self.harness).run_hidden_tests(
            self.hidden_test_dir,
            selected_files=basenames,
        )
        passed = result.passed
        output = result.output

        return GradingResult(
            passed=passed,
            total_hidden_tests=len(hidden_files),
            passed_hidden_tests=len(hidden_files) if passed else 0,
            regression_detected=not passed,
            output=output,
        )
