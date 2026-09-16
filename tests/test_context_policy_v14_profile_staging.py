"""Regression tests for V14's invocation-scoped repository profile staging."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from application.config import ConfigStore


def _load_staging_module():
    path = (
        Path(__file__).parents[1]
        / "eval"
        / "campaigns"
        / "context-policy-multirepo-v14"
        / "profile_staging.py"
    )
    spec = importlib.util.spec_from_file_location("context_policy_v14_profile_staging", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frozen_profile() -> dict:
    return {
        "schema_version": "arc-v14-frozen-repository-profile-v1",
        "campaign_id": "context-policy-multirepo-v14",
        "repository": "click",
        "project_id": "context-policy-multirepo-v14",
        "default_agent": "builder",
        "hard_task_usd": 2.0,
        "hard_project_usd": 350.0,
        "provider_execution_timeout_seconds": 600,
        "visible_test_cmd": ["python", "-m", "pytest", "-q"],
        "visible_test_harness": {"backend": "docker", "image": "arc-v14-click:qualified"},
        "agents": {
            "builder": {
                "name": "builder",
                "provider": "codex",
                "model": "gpt-5.5",
                "role": "implementation",
                "enabled": True,
                "command_override": "codex exec --full-auto --json -",
                "codex_home": "/secure/codex-home",
                "codex_config_path": "/frozen/v14/codex/config.toml",
                "codex_invocation_snapshot_path": "/frozen/v14/codex",
                "codex_invocation_snapshot_sha256": "a" * 64,
                "codex_invocation_snapshot_size": 50,
                "codex_invocation_manifest_path": "/frozen/v14/codex/config-manifest.json",
                "codex_invocation_manifest_sha256": "b" * 64,
                "codex_invocation_codex_version": "codex-cli 0.133.0-alpha.1",
                "codex_invocation_provider": "codex",
                "codex_invocation_authentication_required": True,
                "codex_invocation_semantic_projection": {
                    "model": "gpt-5.5",
                    "model_reasoning_effort": "high",
                },
                "env_allow": [],
                "capabilities": ["implementation", "test", "debug", "refactor"],
                "max_concurrency": 1,
                "cost_weight": 1.0,
                "quality_weight": 1.0,
                "metadata": {},
            }
        },
    }


def test_explicit_profile_load_ignores_stale_ambient_repository_config(tmp_path: Path) -> None:
    staging = _load_staging_module()
    repo = tmp_path / "repo"
    (repo / ".arc").mkdir(parents=True)
    (repo / ".arc" / "config.yaml").write_text(
        "project_id: stale-v11\nagents: {builder: {name: builder, provider: codex, model: wrong}}\n",
        encoding="utf-8",
    )

    staged = staging.stage_frozen_repository_profiles(
        {"click": _frozen_profile()}, tmp_path / "attempt"
    )["click"]
    loaded = ConfigStore.load_explicit(staged.path)

    assert loaded.project_id == "context-policy-multirepo-v14"
    assert loaded.agents["builder"].model == "gpt-5.5"
    assert staged.semantic_parity is True
    assert staged.frozen_profile_digest == staged.staged_profile_digest


def test_missing_staged_profile_fails_closed(tmp_path: Path) -> None:
    staging = _load_staging_module()

    with pytest.raises(staging.ProfileStagingError, match="staged profile is missing"):
        staging.verify_staged_profile(
            tmp_path / "missing.yaml", _frozen_profile(), repository="click"
        )


def test_corrupted_staged_profile_fails_parity(tmp_path: Path) -> None:
    staging = _load_staging_module()
    staged = staging.stage_frozen_repository_profiles(
        {"click": _frozen_profile()}, tmp_path / "attempt"
    )["click"]
    text = staged.path.read_text(encoding="utf-8").replace("gpt-5.5", "wrong-model")
    staged.path.chmod(0o600)
    staged.path.write_text(text, encoding="utf-8")

    with pytest.raises(staging.ProfileStagingError, match="semantic parity"):
        staging.verify_staged_profile(staged.path, _frozen_profile(), repository="click")


def test_malformed_ambient_profile_is_irrelevant_to_explicit_profile(tmp_path: Path) -> None:
    staging = _load_staging_module()
    repo = tmp_path / "repo"
    (repo / ".arc").mkdir(parents=True)
    (repo / ".arc" / "config.yaml").write_text("not: [valid", encoding="utf-8")
    staged = staging.stage_frozen_repository_profiles(
        {"click": _frozen_profile()}, tmp_path / "attempt"
    )["click"]

    profile = staging.load_staged_profile(staged.path, _frozen_profile(), repository="click")

    assert profile.agents["builder"].codex_config_path == "/frozen/v14/codex/config.toml"
