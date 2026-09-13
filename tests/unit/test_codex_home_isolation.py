"""Regression tests for hermetic V4 Codex-home handling."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from application import auth
from application.agents import build_agent
from application.config import AgentProfile, ConfigStore
from application.provider_doctor import passive_provider_doctor

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LOCK_PATH = ROOT / "eval" / "campaigns" / "context-policy-multirepo-v4" / "runtime_lock.py"


def _runtime_lock_module():
    spec = importlib.util.spec_from_file_location("v4_runtime_lock_home", RUNTIME_LOCK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_codex(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli 0.133.0-alpha.1')\n"
        "    raise SystemExit(0)\n"
        "if sys.argv[1:] == ['login', 'status']:\n"
        "    config = pathlib.Path(os.environ['CODEX_HOME']) / 'config.toml'\n"
        "    if 'max' in config.read_text():\n"
        "        print('broken ambient catalog', file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    print('authenticated')\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_auth_status_uses_explicit_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(auth.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(*_args, **kwargs):
        captured["env"] = dict(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="authenticated", stderr="")

    monkeypatch.setattr(auth.subprocess, "run", fake_run)
    result = auth.auth_status("codex", environment={"CODEX_HOME": "/dedicated/v4"})

    assert result.state == "AUTHENTICATED"
    assert captured["env"]["CODEX_HOME"] == "/dedicated/v4"


def test_codex_adapter_overrides_ambient_codex_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", "/broken/ambient-home")
    profile = AgentProfile(
        name="builder",
        provider="codex",
        model="gpt-5.5",
        codex_home="/dedicated/v4-home",
    )

    environment = build_agent(profile).execution_environment()

    assert environment["CODEX_HOME"] == "/dedicated/v4-home"


def test_provider_doctor_ignores_broken_ambient_codex_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ordinary_home = tmp_path / "ordinary-codex-home"
    dedicated_home = tmp_path / "dedicated-codex-home"
    ordinary_home.mkdir()
    dedicated_home.mkdir()
    (ordinary_home / "config.toml").write_text("reasoning = 'max'\n", encoding="utf-8")
    (dedicated_home / "config.toml").write_text("# isolated V4 config\n", encoding="utf-8")
    fake_bin = tmp_path / "codex"
    _fake_codex(fake_bin)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CODEX_HOME", str(ordinary_home))

    report = passive_provider_doctor(
        AgentProfile(
            name="builder",
            provider="codex",
            model="gpt-5.5",
            codex_home=str(dedicated_home),
        )
    )

    assert report.status == "READY"
    assert report.authentication_state == "AUTHENTICATED"
    assert "CODEX_HOME" in report.environment_keys


def test_runtime_lock_binds_codex_home_and_config_digest(tmp_path: Path) -> None:
    module = _runtime_lock_module()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "arc@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "ARC Test"], cwd=repo, check=True)
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "base"],
        cwd=repo,
        check=True,
    )
    arc_repo = tmp_path / "arc"
    arc_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=arc_repo, check=True)
    subprocess.run(["git", "config", "user.email", "arc@example.test"], cwd=arc_repo, check=True)
    subprocess.run(["git", "config", "user.name", "ARC Test"], cwd=arc_repo, check=True)
    (arc_repo / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=arc_repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-qm", "base"],
        cwd=arc_repo,
        check=True,
    )
    provider = tmp_path / "fake-codex"
    _fake_codex(provider)
    home = tmp_path / "dedicated-home"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text("# isolated V4 config\n", encoding="utf-8")

    config = ConfigStore(repo).load("v4-runtime")
    config.provider_execution_timeout_seconds = 600
    config.agents["builder"] = AgentProfile(
        name="builder",
        provider="codex",
        model="gpt-5.5",
        command_override=str(provider),
        codex_home=str(home),
        codex_config_path=str(config_path),
    )
    ConfigStore(repo).save(config)
    lock = tmp_path / "runtime-lock.json"

    module.freeze(repo, "builder", lock, arc_repo, provider_execution_timeout_seconds=600)
    payload = lock.read_text(encoding="utf-8")
    assert str(home) in payload
    assert str(config_path) in payload
    assert "codex_config_sha256" in payload

    config_path.write_text("# changed isolated V4 config\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="runtime contract drift"):
        module.verify(repo, "builder", lock, arc_repo, provider_execution_timeout_seconds=600)
