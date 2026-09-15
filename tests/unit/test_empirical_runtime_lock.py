import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from application.config import AgentProfile, ConfigStore

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK_PATH = (
    ROOT
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v1"
    / "runtime_lock.py"
)


def _runtime_lock_module():
    spec = importlib.util.spec_from_file_location("campaign_runtime_lock", RUNTIME_LOCK_PATH)
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


def _init_git_repo(repo: Path, filename: str = "app.py") -> str:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / filename).write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def _write_fake_provider(path: Path, version: str) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"VERSION = {version!r}\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print(VERSION)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_runtime_lock_detects_provider_arc_commit_and_dirty_tree_drift(tmp_path) -> None:
    module = _runtime_lock_module()
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    arc_repo = tmp_path / "arc-engine"
    frozen_arc_commit = _init_git_repo(arc_repo, "engine.py")

    provider = tmp_path / "fake-codex"
    _write_fake_provider(provider, "fake-codex 1.0.0")
    store = ConfigStore(repo)
    config = store.load("runtime-lock-test")
    config.agents["builder"] = AgentProfile(
        name="builder",
        provider="codex",
        model="gpt-5.3-codex",
        role="implementation",
        capabilities=["implementation", "test", "debug", "refactor"],
        command_override=f"{provider} exec -",
    )
    store.save(config)

    lock_path = tmp_path / "runtime-lock.json"
    module.freeze(repo, "builder", lock_path, arc_repo)
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "arc-empirical-runtime-lock-v4"
    assert payload["provider_cli_version"] == "fake-codex 1.0.0"
    assert payload["arc_commit"] == frozen_arc_commit
    assert payload["arc_worktree_clean"] is True
    module.verify(repo, "builder", lock_path, arc_repo)

    (arc_repo / "engine.py").write_text("VALUE = 99\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="worktree must be clean"):
        module.verify(repo, "builder", lock_path, arc_repo)
    _git(arc_repo, "checkout", "--", "engine.py")
    module.verify(repo, "builder", lock_path, arc_repo)

    _write_fake_provider(provider, "fake-codex 2.0.0")
    with pytest.raises(SystemExit, match="provider_cli_version"):
        module.verify(repo, "builder", lock_path, arc_repo)

    _write_fake_provider(provider, "fake-codex 1.0.0")
    (arc_repo / "engine.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(arc_repo, "add", "engine.py")
    _git(arc_repo, "commit", "-m", "engine drift")
    with pytest.raises(SystemExit, match="arc_commit"):
        module.verify(repo, "builder", lock_path, arc_repo)
