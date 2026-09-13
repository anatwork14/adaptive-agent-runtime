"""Resolve named ARC agent profiles into concrete adapters."""

from __future__ import annotations

import os
import shlex
import shutil
import time
from dataclasses import dataclass
from typing import Optional

from adapters.antigravity import AntigravityAgentAdapter
from adapters.claude import ClaudeAgentAdapter
from adapters.codex import CodexAgentAdapter
from adapters.mock import MockAgentAdapter
from adapters.opencode import OpenCodeAgentAdapter
from adapters.openrouter import OpenRouterAgentAdapter
from application.auth import ProviderAuthStatus, auth_status
from application.config import AgentProfile


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
_AUTH_CACHE: dict[str, tuple[float, ProviderAuthStatus]] = {}


def _cached_auth_status(provider: str) -> ProviderAuthStatus:
    now = time.monotonic()
    cached = _AUTH_CACHE.get(provider)
    if cached and now - cached[0] < _AUTH_CACHE_TTL:
        return cached[1]
    result = auth_status(provider)
    _AUTH_CACHE[provider] = (now, result)
    return result


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
        return CodexAgentAdapter(
            model_name=profile.model,
            command_override=profile.command_override,
            env_allow=profile.env_allow,
            codex_home=profile.codex_home,
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
        return AgentDoctorResult(profile.name, profile.provider, profile.model, None, False, "DISABLED", "profile disabled")
    if profile.provider == "mock":
        return AgentDoctorResult(profile.name, "mock", profile.model, None, True, "READY", "deterministic local smoke-test adapter")
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
    override = profile.command_override or os.environ.get(_PROVIDER_COMMAND_ENV.get(profile.provider, ""), "")
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
        auth = _cached_auth_status(profile.provider)
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
