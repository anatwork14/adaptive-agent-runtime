"""Resolve named ARC agent profiles into concrete adapters."""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import dataclass
from typing import Optional

from adapters.antigravity import AntigravityAgentAdapter
from adapters.claude import ClaudeAgentAdapter
from adapters.codex import CodexAgentAdapter
from adapters.mock import MockAgentAdapter
from adapters.opencode import OpenCodeAgentAdapter
from adapters.openrouter import OpenRouterAgentAdapter
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


def build_agent(profile: AgentProfile):
    """Instantiate a concrete adapter from a named profile."""
    if not profile.enabled:
        raise ValueError(f"Agent profile {profile.name!r} is disabled")

    if profile.command_override:
        env_name = _PROVIDER_COMMAND_ENV.get(profile.provider)
        if env_name:
            os.environ[env_name] = profile.command_override

    if profile.provider == "mock":
        return MockAgentAdapter(profile.name)
    if profile.provider == "codex":
        return CodexAgentAdapter(model_name=profile.model)
    if profile.provider == "claude":
        return ClaudeAgentAdapter(model_name=profile.model)
    if profile.provider == "antigravity":
        return AntigravityAgentAdapter(model_name=profile.model)
    if profile.provider == "opencode":
        return OpenCodeAgentAdapter(model_name=profile.model)
    if profile.provider == "openrouter":
        return OpenRouterAgentAdapter(model_name=profile.model or "openai/gpt-4o-mini")
    raise ValueError(f"Unsupported provider: {profile.provider}")


def doctor_profile(profile: AgentProfile) -> AgentDoctorResult:
    """Perform non-invasive provider readiness checks.

    This checks installation only. Authentication is intentionally handled by
    the separate auth subsystem so status polling does not repeatedly hit
    vendor login endpoints.
    """
    if not profile.enabled:
        return AgentDoctorResult(
            profile.name, profile.provider, profile.model, None, False, "DISABLED", "profile disabled"
        )
    if profile.provider == "mock":
        return AgentDoctorResult(
            profile.name, "mock", profile.model, None, True, "READY", "deterministic local smoke-test adapter"
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
    override = profile.command_override or os.environ.get(_PROVIDER_COMMAND_ENV.get(profile.provider, ""), "")
    if override:
        try:
            executable = shlex.split(override)[0]
        except ValueError:
            pass
    resolved = shutil.which(executable)
    return AgentDoctorResult(
        profile.name,
        profile.provider,
        profile.model,
        executable,
        resolved is not None,
        "READY" if resolved else "MISSING",
        resolved or f"executable {executable!r} not found on PATH",
    )
