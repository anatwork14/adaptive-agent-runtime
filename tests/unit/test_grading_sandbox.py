from pathlib import Path

from eval.grading import hidden_tests
from isolation.container import ExecutionResult, WORKSPACE_PYTHONPATH
from verification.adversarial_tests import AdversarialTestRunner


class _FakeSandbox:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.calls = []

    def run_command(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        return ExecutionResult(
            command=list(command),
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1.0,
        )


def test_visible_tests_force_candidate_source_ahead_of_site_packages(tmp_path) -> None:
    runner = AdversarialTestRunner(tmp_path)
    fake = _FakeSandbox(tmp_path)
    runner.sandbox = fake

    result = runner.run_tests(["python", "-m", "pytest", "-q"])

    assert result.passed is True
    command, kwargs = fake.calls[0]
    assert command == ["python", "-m", "pytest", "-q"]
    assert kwargs["env_vars"] == {
        "PYTHONPATH": WORKSPACE_PYTHONPATH,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def test_hidden_tests_use_same_sandbox_and_read_only_external_mount(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden_task.py").write_text("def test_ok(): assert True\n", encoding="utf-8")

    created = []

    class FakeSandbox(_FakeSandbox):
        def __init__(self, workspace_path):
            super().__init__(Path(workspace_path))
            created.append(self)

    monkeypatch.setattr(hidden_tests, "SandboxRunner", FakeSandbox)
    grader = hidden_tests.HiddenTestGrader(hidden)
    grade = grader.grade(workspace, "test_hidden_*.py")

    assert grade.passed is True
    assert grade.total_hidden_tests == 1
    command, kwargs = created[0].calls[0]
    assert command == [
        "python",
        "-m",
        "pytest",
        "-v",
        "/arc-hidden-tests/test_hidden_task.py",
    ]
    assert kwargs["env_vars"] == {
        "PYTHONPATH": WORKSPACE_PYTHONPATH,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert kwargs["read_only_mounts"] == {hidden.resolve(): "/arc-hidden-tests"}
