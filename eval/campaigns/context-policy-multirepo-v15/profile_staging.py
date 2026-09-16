"""Deterministic, attempt-scoped staging for frozen V15 repository profiles."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from application.config import ArcConfig, ConfigStore


class ProfileStagingError(RuntimeError):
    """A frozen profile could not be staged or verified."""


@dataclass(frozen=True)
class StagedProfile:
    repository: str
    path: Path
    frozen_profile_digest: str
    staged_profile_digest: str
    serialized_sha256: str
    semantic_parity: bool


def build_frozen_profile_payload(
    contract: dict[str, Any],
    plan: Any,
    *,
    repository: str,
) -> dict[str, Any]:
    """Construct the canonical frozen ARC profile from contract and plan data."""
    provider_contract = contract["provider_profile"]
    provider_runtime = contract["provider_runtime"]
    runtime = plan.runtime
    return {
        "schema_version": "arc-v15-frozen-repository-profile-v1",
        "campaign_id": contract["campaign_id"],
        "repository": repository,
        "project_id": contract["campaign_id"],
        "default_agent": runtime.agent_profile,
        "hard_task_usd": contract["shared_protocol"]["hard_task_usd"],
        "hard_project_usd": runtime.hard_project_usd,
        "provider_execution_timeout_seconds": runtime.provider_execution_timeout_seconds,
        "visible_test_cmd": list(runtime.visible_test_cmd),
        "visible_test_harness": runtime.visible_test_harness.model_dump(mode="json"),
        "orchestration_max_parallel": 3,
        "routing_policy": "balanced",
        "agents": {
            runtime.agent_profile: {
                "name": runtime.agent_profile,
                "provider": runtime.provider,
                "model": runtime.model,
                "role": runtime.profile_role,
                "enabled": True,
                "command_override": provider_contract["command_override"],
                "codex_home": provider_runtime["codex_home"],
                "codex_config_path": runtime.provider_codex_config_path,
                "codex_invocation_snapshot_path": runtime.provider_codex_snapshot_path,
                "codex_invocation_snapshot_sha256": runtime.provider_codex_snapshot_sha256,
                "codex_invocation_snapshot_size": runtime.provider_codex_snapshot_size,
                "codex_invocation_manifest_path": runtime.provider_codex_manifest_path,
                "codex_invocation_manifest_sha256": runtime.provider_codex_manifest_sha256,
                "codex_invocation_codex_version": runtime.provider_codex_version,
                "codex_invocation_provider": runtime.provider_codex_provider,
                "codex_invocation_authentication_required": runtime.provider_codex_authentication_required,
                "codex_invocation_semantic_projection": dict(runtime.provider_codex_semantic_projection),
                "env_allow": [],
                "capabilities": list(runtime.profile_capabilities),
                "max_concurrency": 1,
                "cost_weight": 1.0,
                "quality_weight": 1.0,
                "metadata": {},
            }
        },
    }


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def normalize_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the exact semantic representation accepted by ``ArcConfig``."""
    try:
        return ArcConfig.model_validate(payload).model_dump(mode="json", exclude_none=True)
    except Exception as exc:  # pragma: no cover - specific validation is reported below
        raise ProfileStagingError(f"frozen profile is invalid: {exc}") from exc


def frozen_profile_digest(payload: dict[str, Any]) -> str:
    """Digest the normalized semantic frozen profile representation."""
    return _digest(normalize_profile_payload(payload))


def verify_staged_profile(
    path: str | Path,
    frozen_payload: dict[str, Any],
    *,
    repository: str,
) -> StagedProfile:
    """Verify a staged profile against the frozen semantic payload."""
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ProfileStagingError(f"staged profile is missing for {repository}: {profile_path}")
    expected = normalize_profile_payload(frozen_payload)
    expected_digest = frozen_profile_digest(frozen_payload)
    try:
        actual_config = ConfigStore.load_explicit(profile_path)
    except Exception as exc:
        raise ProfileStagingError(
            f"staged profile is invalid for {repository}: {profile_path}: {exc}"
        ) from exc
    actual = actual_config.model_dump(mode="json", exclude_none=True)
    actual_digest = _digest(actual)
    if actual != expected:
        raise ProfileStagingError(
            f"staged profile semantic parity failure for {repository}: {profile_path}"
        )
    return StagedProfile(
        repository=repository,
        path=profile_path,
        frozen_profile_digest=expected_digest,
        staged_profile_digest=actual_digest,
        serialized_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        semantic_parity=True,
    )


def load_staged_profile(
    path: str | Path,
    frozen_payload: dict[str, Any],
    *,
    repository: str,
):
    """Verify then load the explicit staged profile; ambient state is ignored."""
    verify_staged_profile(path, frozen_payload, repository=repository)
    return ConfigStore.load_explicit(path)


def stage_frozen_repository_profiles(
    frozen_profiles: dict[str, dict[str, Any]],
    attempt_root: str | Path,
) -> dict[str, StagedProfile]:
    """Materialize exact frozen profiles below one disposable attempt root."""
    root = Path(attempt_root).expanduser().resolve() / "profiles"
    root.mkdir(parents=True, exist_ok=True)
    staged: dict[str, StagedProfile] = {}
    for repository, payload in frozen_profiles.items():
        if not repository or "/" in repository or "\\" in repository:
            raise ProfileStagingError(f"invalid repository profile key: {repository!r}")
        profile_path = root / repository / "config.yaml"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(
            payload,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        ).encode("utf-8")
        if profile_path.exists():
            if profile_path.read_bytes() != serialized:
                raise ProfileStagingError(
                    f"existing staged profile differs for {repository}: {profile_path}"
                )
        else:
            temporary = profile_path.with_name(profile_path.name + ".tmp")
            temporary.write_bytes(serialized)
            with temporary.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(profile_path)
        profile_path.chmod(0o444)
        staged[repository] = verify_staged_profile(
            profile_path,
            payload,
            repository=repository,
        )
    return staged
