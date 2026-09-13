from __future__ import annotations

from pathlib import Path

from eval.grading import hidden_tests as hidden_tests_module
from eval.grading.hidden_tests import HiddenTestGrader
from isolation.container import ExecutionResult
from verification.adversarial_tests import AdversarialTestResult, AdversarialTestRunner

HARNESS = {
    "backend": "docker",
    "image": "arc-qualified:test",
    "image_digest": "sha256:" + "a" * 64,
    "hidden_command": ["python", "-m", "pytest", "-q", "/arc-hidden-tests"],
    "hidden_environment": {"PYTHONPATH": "/workspace"},
    "tmpfs_exec": False,
    "timeout_seconds": 60,
}


def _hidden_fixture(root: Path) -> Path:
    hidden = root / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden_t001_a.py").write_text("assert True\n", encoding="utf-8")
    (hidden / "test_hidden_t002_a.py").write_text("assert False\n", encoding="utf-8")
    (hidden / "test_hidden_t003_a.py").write_text("assert False\n", encoding="utf-8")
    return hidden


def test_hidden_grader_scopes_selection_to_one_task(monkeypatch, tmp_path: Path) -> None:
    hidden = _hidden_fixture(tmp_path)
    calls: list[list[str]] = []

    class FakeRunner:
        def __init__(self, workspace_path, *, harness):
            assert Path(workspace_path) == (tmp_path / "candidate").resolve()
            assert harness == HARNESS

        def run_hidden_tests(self, hidden_test_dir, *, selected_files):
            calls.append(list(selected_files))
            passed = selected_files == ["test_hidden_t001_a.py"]
            return AdversarialTestResult(
                passed=passed,
                total_tests=len(selected_files),
                failed_tests=0 if passed else len(selected_files),
                output="synthetic hidden result",
            )

    monkeypatch.setattr(hidden_tests_module, "AdversarialTestRunner", FakeRunner)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    grader = HiddenTestGrader(hidden, harness=HARNESS, hidden_tests_required=True)

    passed = grader.grade(candidate, test_file_pattern="test_hidden_t001_*.py")
    failed = grader.grade(candidate, test_file_pattern="test_hidden_t002_*.py")

    assert passed.passed is True
    assert passed.total_hidden_tests == 1
    assert failed.passed is False
    assert failed.total_hidden_tests == 1
    assert calls == [["test_hidden_t001_a.py"], ["test_hidden_t002_a.py"]]


def test_hidden_grader_fails_closed_on_zero_required_matches(tmp_path: Path) -> None:
    hidden = _hidden_fixture(tmp_path)
    grader = HiddenTestGrader(
        hidden,
        harness=HARNESS,
        hidden_tests_required=True,
    )

    result = grader.grade(tmp_path, test_file_pattern="test_hidden_missing_*.py")

    assert result.passed is False
    assert result.total_hidden_tests == 0
    assert "refusing to grade an empty selection" in result.output


def test_hidden_grader_never_falls_back_to_host_python(tmp_path: Path) -> None:
    hidden = _hidden_fixture(tmp_path)
    grader = HiddenTestGrader(hidden, hidden_tests_required=True)

    result = grader.grade(tmp_path, test_file_pattern="test_hidden_t001_*.py")

    assert result.passed is False
    assert "host-Python fallback is disabled" in result.output


def test_container_hidden_runner_passes_only_selected_paths(monkeypatch, tmp_path: Path) -> None:
    hidden = _hidden_fixture(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    runner = AdversarialTestRunner(candidate, harness=HARNESS)
    captured: dict[str, object] = {}

    def fake_run_command(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return ExecutionResult(
            command=command,
            exit_code=0,
            stdout="1 passed",
            stderr="",
            duration_ms=1.0,
        )

    monkeypatch.setattr(runner.sandbox, "run_command", fake_run_command)
    result = runner.run_hidden_tests(
        hidden,
        selected_files=["test_hidden_t001_a.py"],
    )

    assert result.passed is True
    assert captured["command"][-1] == "/arc-hidden-tests/test_hidden_t001_a.py"
    assert "/arc-hidden-tests" not in captured["command"][:-1]
    assert captured["read_only_mounts"] == {"/arc-hidden-tests": hidden.resolve()}
    assert captured["workspace_read_only"] is True
