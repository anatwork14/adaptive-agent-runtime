import importlib.util
import subprocess
from pathlib import Path

import pytest

from isolation.container import ExecutionResult, WORKSPACE_PYTHONPATH


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = (
    ROOT
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v1"
    / "grading_preflight.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("campaign_grading_preflight", PREFLIGHT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_preflight_requires_candidate_local_import_and_passing_visible_suite(
    tmp_path, monkeypatch
) -> None:
    module = _module()
    repo, commit = _repo(tmp_path)
    calls = []

    class FakeSandbox:
        def __init__(self, workspace_path, timeout_seconds=120):
            self.workspace_path = Path(workspace_path)
            self.timeout_seconds = timeout_seconds

        def run_command(self, command, **kwargs):
            calls.append((list(command), dict(kwargs)))
            if command[:2] == ["python", "-c"]:
                return ExecutionResult(
                    command=list(command),
                    exit_code=0,
                    stdout="/workspace/src/demo/__init__.py\n",
                    stderr="",
                    duration_ms=3.0,
                )
            return ExecutionResult(
                command=list(command),
                exit_code=0,
                stdout="12 passed\n",
                stderr="",
                duration_ms=42.0,
            )

    monkeypatch.setattr(module, "SandboxRunner", FakeSandbox)
    report = module.validate_base_grading_environment(
        repo,
        commit=commit,
        visible_test_cmd=["python", "-m", "pytest", "-q"],
        import_module="demo",
        expected_import_prefix="/workspace/src/demo/",
    )

    assert report["repo_commit"] == commit
    assert report["imported_from"] == "/workspace/src/demo/__init__.py"
    assert report["pythonpath"] == WORKSPACE_PYTHONPATH
    assert report["visible_tests_passed"] is True
    assert report["visible_test_duration_ms"] == 42.0
    assert calls[0][1]["env_vars"]["PYTHONPATH"] == WORKSPACE_PYTHONPATH
    assert calls[1][0] == ["python", "-m", "pytest", "-q"]
    assert _git(repo, "status", "--porcelain") == ""


def test_preflight_rejects_site_packages_import_and_cleans_worktree(
    tmp_path, monkeypatch
) -> None:
    module = _module()
    repo, commit = _repo(tmp_path)

    class WrongImportSandbox:
        def __init__(self, workspace_path, timeout_seconds=120):
            pass

        def run_command(self, command, **kwargs):
            return ExecutionResult(
                command=list(command),
                exit_code=0,
                stdout="/usr/local/lib/python3.11/site-packages/demo/__init__.py\n",
                stderr="",
                duration_ms=1.0,
            )

    monkeypatch.setattr(module, "SandboxRunner", WrongImportSandbox)
    with pytest.raises(RuntimeError, match="escaped mounted source"):
        module.validate_base_grading_environment(
            repo,
            commit=commit,
            visible_test_cmd=["python", "-m", "pytest", "-q"],
            import_module="demo",
            expected_import_prefix="/workspace/src/demo/",
        )

    assert _git(repo, "status", "--porcelain") == ""
    worktrees = _git(repo, "worktree", "list", "--porcelain")
    assert "arc-grading-preflight-" not in worktrees
