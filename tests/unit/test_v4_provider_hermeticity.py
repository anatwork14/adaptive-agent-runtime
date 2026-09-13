"""V4 execution-loop provider-home and config-drift regressions."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.base import AgentBudget
from adapters.codex import CodexAgentAdapter
from application import agents
from application.auth import ProviderAuthStatus
from application.config import AgentProfile

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_DIR = ROOT / "eval" / "campaigns" / "context-policy-multirepo-v4"


def _execution_module():
    path = CAMPAIGN_DIR / "execute_campaign.py"
    spec = importlib.util.spec_from_file_location("v4_execute_provider_hermeticity", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _authenticated(provider: str) -> ProviderAuthStatus:
    return ProviderAuthStatus(
        provider=provider,
        display_name="Codex",
        installed=True,
        authenticated=True,
        state="AUTHENTICATED",
        detail="authenticated",
        executable="codex",
        auth_method="OAuth",
    )


def test_agent_doctor_cache_separates_codex_homes(monkeypatch: pytest.MonkeyPatch) -> None:
    agents._AUTH_CACHE.clear()
    calls: list[dict[str, str] | None] = []

    def fake_auth_status(provider: str, *, environment=None):
        assert provider == "codex"
        calls.append(environment)
        return _authenticated(provider)

    monkeypatch.setattr(agents, "auth_status", fake_auth_status)
    monkeypatch.setattr(agents.shutil, "which", lambda _name: "/usr/bin/codex")

    profile_a = AgentProfile(
        name="builder-a",
        provider="codex",
        model="gpt-5.5",
        codex_home="/dedicated/v4-a",
    )
    profile_b = profile_a.model_copy(update={"name": "builder-b", "codex_home": "/dedicated/v4-b"})

    assert agents.doctor_profile(profile_a).status == "READY"
    assert agents.doctor_profile(profile_b).status == "READY"
    assert agents.doctor_profile(profile_a).status == "READY"

    assert calls == [
        {"CODEX_HOME": "/dedicated/v4-a"},
        {"CODEX_HOME": "/dedicated/v4-b"},
    ]
    agents._AUTH_CACHE.clear()


@pytest.mark.parametrize("mutate_after", [None, "click"])
def test_v4_execution_loop_authenticates_each_repository_with_frozen_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate_after: str | None
) -> None:
    module = _execution_module()
    home = tmp_path / "codex-home"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text("trusted = true\n", encoding="utf-8")
    config_sha = module._sha256_file(config_path)
    contract = {
        "campaign_id": "context-policy-multirepo-v4",
        "provider_profile": {"provider": "codex"},
        "provider_runtime": {
            "codex_home": str(home),
            "codex_config_path": str(config_path),
            "codex_config_sha256": config_sha,
        },
    }
    freeze_manifest = {
        "runtime_lock": "runtime-lock.json",
        "meta_plan": "meta-plan.json",
        "repository_plans": {slug: {"path": f"{slug}.json"} for slug in module.REPOSITORY_ORDER},
    }
    plans = {
        slug: SimpleNamespace(
            plan_digest=f"digest-{slug}",
            benchmark_id=f"benchmark-{slug}",
            study_id=f"study-{slug}",
        )
        for slug in module.REPOSITORY_ORDER
    }
    meta = SimpleNamespace(plan_digest="meta-digest")
    results_root = tmp_path / "results"
    workspace_root = tmp_path / "runtime"
    execution_root = results_root / contract["campaign_id"] / "a001"
    execution_workspace = workspace_root / contract["campaign_id"] / "a001"
    monkeypatch.setattr(module, "_load_contract", lambda: contract)
    monkeypatch.setattr(
        module,
        "_load_freeze_bundle",
        lambda _freeze_dir, _contract: (freeze_manifest, {}, meta, plans),
    )
    monkeypatch.setattr(
        module,
        "preflight_campaign",
        lambda *_args, **_kwargs: {
            "execution_root": str(execution_root),
            "workspace_root": str(execution_workspace),
            "arc_commit": "arc-commit",
            "freeze_manifest_sha256": "freeze-sha",
            "runtime_lock_digest": "runtime-sha",
            "provider_cli_version": "codex-cli 0.133.0-alpha.1",
            "provider_execution_timeout_seconds": 600,
            "provider_auth": {"state": "AUTHENTICATED"},
            "ready_for_execution": True,
        },
    )
    monkeypatch.setattr(module, "_validate_live_repository", lambda *_args, **_kwargs: {})
    auth_environments: list[dict[str, str]] = []

    def fake_auth_status(provider: str, *, environment=None):
        assert provider == "codex"
        auth_environments.append(dict(environment or {}))
        return _authenticated(provider)

    monkeypatch.setattr(module, "auth_status", fake_auth_status)

    def fake_run_logged(args: list[str], *, log_path: Path) -> None:
        if "run-plan" in args:
            output_root = Path(args[args.index("--output-root") + 1])
            slug = Path(args[args.index("--repo") + 1]).name
            plan = plans[slug]
            study_dir = module._study_dir(output_root, plan, "a001")
            study_dir.mkdir(parents=True)
            (study_dir / "study.json").write_text("{}\n", encoding="utf-8")
            (study_dir / "provenance.json").write_text(
                json.dumps({"extra": {"plan_digest": plan.plan_digest}}) + "\n",
                encoding="utf-8",
            )
            if slug == mutate_after:
                config_path.write_text("provider mutation\n", encoding="utf-8")
        elif "export" in args:
            export_dir = Path(args[args.index("--output-dir") + 1])
            export_dir.mkdir(parents=True)
            (export_dir / "export_manifest.json").write_text("{}\n", encoding="utf-8")
        else:
            meta_output = Path(args[args.index("--output-dir") + 1])
            meta_output.mkdir(parents=True)
            (meta_output / "meta_study.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(module, "_run_logged", fake_run_logged)
    repos = {slug: tmp_path / slug for slug in module.REPOSITORY_ORDER}

    if mutate_after == "click":
        with pytest.raises(RuntimeError, match="provider config drift detected"):
            module.execute_campaign(
                repos,
                hidden_root=tmp_path / "hidden",
                freeze_dir=tmp_path / "freeze",
                results_root=results_root,
                workspace_root=workspace_root,
                attempt_id="a001",
            )
        assert auth_environments == [{"CODEX_HOME": str(home)}]
        ledger = json.loads(
            (execution_root / "execution-manifest.json").read_text(encoding="utf-8")
        )
        assert ledger["repositories"]["httpx"]["status"] == "PENDING"
        return

    module.execute_campaign(
        repos,
        hidden_root=tmp_path / "hidden",
        freeze_dir=tmp_path / "freeze",
        results_root=results_root,
        workspace_root=workspace_root,
        attempt_id="a001",
    )

    assert auth_environments == [{"CODEX_HOME": str(home)}] * 3
    ledger = json.loads((execution_root / "execution-manifest.json").read_text(encoding="utf-8"))
    for slug in module.REPOSITORY_ORDER:
        state = ledger["repositories"][slug]
        assert state["provider_runtime_before"]["actual_codex_home"] == str(home)
        assert state["provider_runtime_after"]["actual_codex_home"] == str(home)
        assert state["provider_runtime_after"]["actual_config_sha256"] == config_sha


def test_v4_provider_config_drift_fails_closed(tmp_path: Path) -> None:
    module = _execution_module()
    home = tmp_path / "codex-home"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text("H1\n", encoding="utf-8")
    contract = {
        "provider_runtime": {
            "codex_home": str(home),
            "codex_config_path": str(config_path),
            "codex_config_sha256": module._sha256_file(config_path),
        }
    }

    stable = module._validate_provider_runtime_identity(contract, phase="before_click")
    assert stable["verified"] is True

    config_path.write_text("H2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="provider config drift detected"):
        module._validate_provider_runtime_identity(contract, phase="after_click")


def test_codex_provider_turn_uses_and_discards_mutable_invocation_home(tmp_path: Path) -> None:
    home = tmp_path / "canonical-codex-home"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text("canonical = true\n", encoding="utf-8")
    auth_path = home / "auth.json"
    auth_path.write_text("vendor-auth-state\n", encoding="utf-8")
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "home = pathlib.Path(os.environ['CODEX_HOME'])\n"
        "print('INVOCATION_HOME=' + str(home), flush=True)\n"
        "print('AUTH_PRESENT=' + str((home / 'auth.json').is_file()), flush=True)\n"
        "print(json.dumps({'type': 'turn.started'}), flush=True)\n"
        "print(json.dumps({'type': 'item.started', 'item': {'type': 'agent_message'}}), flush=True)\n"
        "(home / 'config.toml').open('a', encoding='utf-8').write('mutated = true\\n')\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {'output_tokens': 1}}), flush=True)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    adapter = CodexAgentAdapter(
        model_name="gpt-5.5",
        command_override=str(fake),
        codex_home=str(home),
        codex_config_path=str(config_path),
    )
    result = asyncio.run(
        adapter.run_prompt(
            prompt="reply",
            workspace=workspace,
            budget=AgentBudget(timeout_seconds=5),
        )
    )

    assert result.status == "completed"
    assert result.provider_lifecycle["request_started"] == "observed"
    assert result.provider_lifecycle["response_started"] == "observed"
    assert result.provider_lifecycle["completed"] == "observed"
    assert config_path.read_text(encoding="utf-8") == "canonical = true\n"
    assert auth_path.read_text(encoding="utf-8") == "vendor-auth-state\n"
    invocation_home = next(
        line.split("=", 1)[1]
        for line in result.stdout_tail.splitlines()
        if line.startswith("INVOCATION_HOME=")
    )
    assert "arc-codex-v4-invocation-" in invocation_home
    assert not Path(invocation_home).exists()
    assert "AUTH_PRESENT=True" in result.stdout_tail
