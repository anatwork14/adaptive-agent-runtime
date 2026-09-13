"""V4 runtime-lock checks for the explicit provider execution timeout."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from application.config import AgentProfile, ConfigStore

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK_PATH = ROOT / "eval" / "campaigns" / "context-policy-multirepo-v4" / "runtime_lock.py"


def _runtime_lock_module():
    spec = importlib.util.spec_from_file_location("v4_runtime_lock", RUNTIME_LOCK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, filename: str) -> str:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / filename).write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-qm", "base")
    return _git(repo, "rev-parse", "HEAD")


def _fake_provider(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('fake-codex 1.0.0')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_v4_runtime_lock_freezes_and_verifies_provider_timeout(tmp_path: Path) -> None:
    module = _runtime_lock_module()
    repo = tmp_path / "repo"
    _init_repo(repo, "app.py")
    arc_repo = tmp_path / "arc"
    arc_commit = _init_repo(arc_repo, "engine.py")
    provider = tmp_path / "fake-codex"
    _fake_provider(provider)

    config = ConfigStore(repo).load("v4-runtime")
    config.provider_execution_timeout_seconds = 600
    config.agents["builder"] = AgentProfile(
        name="builder",
        provider="codex",
        model="gpt-5.5",
        command_override=str(provider),
        capabilities=["implementation", "test", "debug", "refactor"],
    )
    ConfigStore(repo).save(config)

    lock = tmp_path / "runtime-lock.json"
    module.freeze(
        repo,
        "builder",
        lock,
        arc_repo,
        provider_execution_timeout_seconds=600,
    )
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "arc-empirical-runtime-lock-v5"
    assert payload["provider_execution_timeout_seconds"] == 600
    assert payload["arc_commit"] == arc_commit
    module.verify(
        repo,
        "builder",
        lock,
        arc_repo,
        provider_execution_timeout_seconds=600,
    )

    config.provider_execution_timeout_seconds = 599
    ConfigStore(repo).save(config)
    with pytest.raises(SystemExit, match="runtime contract drift"):
        module.verify(
            repo,
            "builder",
            lock,
            arc_repo,
            provider_execution_timeout_seconds=600,
        )
