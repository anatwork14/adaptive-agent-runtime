"""Resolve named ARC agent profiles into concrete adapters."""

from __future__ import annotations

import os
import shlex
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from adapters.antigravity import AntigravityAgentAdapter
from adapters.claude import ClaudeAgentAdapter
from adapters.codex import CodexAgentAdapter
from adapters.mock import MockAgentAdapter
from adapters.opencode import OpenCodeAgentAdapter
from adapters.openrouter import OpenRouterAgentAdapter
from application.auth import ProviderAuthStatus, auth_status
from application.config import AgentProfile
from runtime.codex_invocation_config import (
    CodexInvocationConfig,
    ConfigContractError,
    verify_snapshot,
)


@dataclass(frozen=True)
class AgentDoctorResult:
    name: str
    provider: str
    model: Optional[str]
    executable: Optional[str]
    installed: bool
    status: str
    detail: str


_PROVIDER_EXECUTABLES = {
    "codex": "codex",
    "claude": "claude",
    "antigravity": "agy",
    "opencode": "opencode",
}

_PROVIDER_COMMAND_ENV = {
    "codex": "ARC_CODEX_COMMAND",
    "claude": "ARC_CLAUDE_COMMAND",
    "opencode": "ARC_OPENCODE_COMMAND",
}

_AUTH_CACHE_TTL = 30.0
_AUTH_CACHE: dict[tuple[str, str | None], tuple[float, ProviderAuthStatus]] = {}


def _cached_auth_status(
    provider: str,
    *,
    environment: dict[str, str] | None = None,
) -> ProviderAuthStatus:
    now = time.monotonic()
    cache_key = (provider, (environment or {}).get("CODEX_HOME"))
    cached = _AUTH_CACHE.get(cache_key)
    if cached and now - cached[0] < _AUTH_CACHE_TTL:
        return cached[1]
    result = auth_status(provider, environment=environment)
    _AUTH_CACHE[cache_key] = (now, result)
    return result


def profile_invocation_config(
    profile: AgentProfile,
    *,
    require_complete: bool = False,
) -> CodexInvocationConfig | None:
    """Reconstruct the one canonical Codex contract stored in a profile.

    A campaign-bound profile must carry every field.  No ambient environment
    value is eligible to complete a persisted contract.
    """
    if profile.provider != "codex":
        return None
    fields = {
        "codex_invocation_snapshot_path": profile.codex_invocation_snapshot_path,
        "codex_invocation_snapshot_sha256": profile.codex_invocation_snapshot_sha256,
        "codex_invocation_snapshot_size": profile.codex_invocation_snapshot_size,
        "codex_invocation_manifest_path": profile.codex_invocation_manifest_path,
        "codex_invocation_manifest_sha256": profile.codex_invocation_manifest_sha256,
        "codex_invocation_codex_version": profile.codex_invocation_codex_version,
        "codex_invocation_provider": profile.codex_invocation_provider,
        "codex_invocation_authentication_required": profile.codex_invocation_authentication_required,
        "codex_invocation_semantic_projection": profile.codex_invocation_semantic_projection,
    }
    present = any(value not in (None, "", {}) for value in fields.values())
    if not present and not require_complete:
        return None
    missing = [name for name, value in fields.items() if value in (None, "", {})]
    if missing:
        raise ConfigContractError(
            "codex profile invocation contract is incomplete: " + ", ".join(missing)
        )
    try:
        contract = CodexInvocationConfig(
            snapshot_path=Path(str(fields["codex_invocation_snapshot_path"])).expanduser().resolve(),
            snapshot_sha256=str(fields["codex_invocation_snapshot_sha256"]),
            snapshot_size=int(fields["codex_invocation_snapshot_size"]),
            codex_version=str(fields["codex_invocation_codex_version"]),
            semantic_projection=dict(fields["codex_invocation_semantic_projection"]),
            provider=str(fields["codex_invocation_provider"]),
            authentication_required=bool(fields["codex_invocation_authentication_required"]),
            manifest_path=Path(str(fields["codex_invocation_manifest_path"])).expanduser().resolve(),
            manifest_sha256=str(fields["codex_invocation_manifest_sha256"]),
        )
        verify_snapshot(contract)
        return contract
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, ConfigContractError):
            raise
        raise ConfigContractError("codex profile invocation contract is invalid") from exc


def build_agent(profile: AgentProfile):
    """Instantiate a concrete adapter from a named profile.

    Command overrides are passed directly to the adapter. ARC never mutates the
    parent process environment merely to configure one worker, which prevents a
    profile-local override from leaking into concurrently constructed agents.
    """
    if not profile.enabled:
        raise ValueError(f"Agent profile {profile.name!r} is disabled")

    if profile.provider == "mock":
        return MockAgentAdapter(profile.name)
    if profile.provider == "codex":
        invocation_config = profile_invocation_config(
            profile, require_complete=profile.codex_invocation_snapshot_path is not None
        )
        return CodexAgentAdapter(
            model_name=profile.model,
            command_override=profile.command_override,
            env_allow=profile.env_allow,
            codex_home=profile.codex_home,
            codex_config_path=profile.codex_config_path,
            invocation_config=invocation_config,
            auth_source=(
                str(Path(profile.codex_home) / "auth.json")
                if profile.codex_home
                else None
            ),
        )
    if profile.provider == "claude":
        return ClaudeAgentAdapter(
            model_name=profile.model,
            command_override=profile.command_override,
            env_allow=profile.env_allow,
        )
    if profile.provider == "antigravity":
        return AntigravityAgentAdapter(model_name=profile.model, env_allow=profile.env_allow)
    if profile.provider == "opencode":
        return OpenCodeAgentAdapter(
            model_name=profile.model,
            command_override=profile.command_override,
            env_allow=profile.env_allow,
        )
    if profile.provider == "openrouter":
        return OpenRouterAgentAdapter(model_name=profile.model or "openai/gpt-4o-mini")
    raise ValueError(f"Unsupported provider: {profile.provider}")


def doctor_profile(profile: AgentProfile) -> AgentDoctorResult:
    """Check installation plus vendor-native authentication where supported."""
    if not profile.enabled:
        return AgentDoctorResult(
            profile.name,
            profile.provider,
            profile.model,
            None,
            False,
            "DISABLED",
            "profile disabled",
        )
    if profile.provider == "mock":
        return AgentDoctorResult(
            profile.name,
            "mock",
            profile.model,
            None,
            True,
            "READY",
            "deterministic local smoke-test adapter",
        )
    if profile.provider == "openrouter":
        has_key = bool(os.environ.get("OPENROUTER_API_KEY"))
        return AgentDoctorResult(
            profile.name,
            "openrouter",
            profile.model,
            None,
            has_key,
            "GATEWAY_ONLY" if has_key else "UNCONFIGURED",
            "OpenRouter is a model gateway; ARC does not yet expose it as a filesystem executor",
        )

    executable = _PROVIDER_EXECUTABLES[profile.provider]
    override = profile.command_override or os.environ.get(
        _PROVIDER_COMMAND_ENV.get(profile.provider, ""), ""
    )
    if override:
        try:
            executable = shlex.split(override)[0]
        except ValueError:
            pass
    resolved = shutil.which(executable)
    if not resolved:
        return AgentDoctorResult(
            profile.name,
            profile.provider,
            profile.model,
            executable,
            False,
            "MISSING",
            f"executable {executable!r} not found on PATH",
        )

    if profile.provider in {"codex", "claude", "antigravity"} and not override:
        provider_environment = (
            {"CODEX_HOME": profile.codex_home}
            if profile.provider == "codex" and profile.codex_home
            else None
        )
        auth = _cached_auth_status(profile.provider, environment=provider_environment)
        return AgentDoctorResult(
            profile.name,
            profile.provider,
            profile.model,
            executable,
            True,
            "READY" if auth.authenticated else "AUTH_REQUIRED",
            auth.detail,
        )

    return AgentDoctorResult(
        profile.name,
        profile.provider,
        profile.model,
        executable,
        True,
        "READY",
        resolved,
    )
