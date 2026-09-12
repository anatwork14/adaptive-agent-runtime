"""Security regression tests for ARC-managed child-process environments."""

from __future__ import annotations

import os
import subprocess

import pytest
from pydantic import ValidationError

from application.agents import build_agent
from application.config import AgentProfile
from runtime.environment import build_execution_environment, redact_command
from runtime.tmux import TmuxController


def test_provider_environment_excludes_unrelated_host_secrets() -> None:
    source = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/arc",
        "OPENAI_API_KEY": "openai-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "DATABASE_URL": "postgres://secret",
        "CUSTOM_TOOL_HOME": "/opt/tool",
    }

    env = build_execution_environment(
        provider="codex",
        extra_names=["CUSTOM_TOOL_HOME"],
        source=source,
    )

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/arc"
    assert env["OPENAI_API_KEY"] == "openai-secret"
    assert env["CUSTOM_TOOL_HOME"] == "/opt/tool"
    assert "ANTHROPIC_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "DATABASE_URL" not in env


def test_preview_environment_has_no_provider_credentials() -> None:
    source = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/arc",
        "OPENAI_API_KEY": "openai-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "OPENROUTER_API_KEY": "router-secret",
    }
    env = build_execution_environment(source=source)
    assert env == {"HOME": "/home/arc", "PATH": "/usr/bin:/bin"}


def test_agent_profile_only_persists_environment_names() -> None:
    profile = AgentProfile(
        name="builder",
        provider="codex",
        env_allow=["CUSTOM_TOKEN", "CUSTOM_TOKEN", "TOOL_HOME"],
    )
    assert profile.env_allow == ["CUSTOM_TOKEN", "TOOL_HOME"]
    payload = profile.model_dump(mode="json")
    assert payload["env_allow"] == ["CUSTOM_TOKEN", "TOOL_HOME"]
    assert "secret-value" not in str(payload)

    with pytest.raises(ValidationError):
        AgentProfile(name="bad", provider="codex", env_allow=["BAD-NAME=secret-value"])


def test_profile_command_override_does_not_mutate_parent_environment(monkeypatch) -> None:
    monkeypatch.delenv("ARC_CODEX_COMMAND", raising=False)
    profile = AgentProfile(
        name="builder",
        provider="codex",
        command_override="python -V",
    )
    adapter = build_agent(profile)
    assert adapter.build_command() == ["python", "-V"]
    assert "ARC_CODEX_COMMAND" not in os.environ


def test_command_trace_redacts_obvious_secret_arguments() -> None:
    assert redact_command(
        ["tool", "--api-key=abc123", "--token", "def456", "--safe", "value"]
    ) == ["tool", "--api-key=<redacted>", "--token", "<redacted>", "--safe", "value"]


def test_tmux_start_uses_clean_environment_boundary(tmp_path, monkeypatch) -> None:
    controller = TmuxController("tmux")
    calls: list[list[str]] = []

    def fake_run(args, *, check=True, interactive=False):
        calls.append(list(args))
        if args and args[0] == "has-session":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run", fake_run)
    controller.start(
        name="arc-terminal-test",
        cwd=tmp_path,
        command=["python", "-V"],
        environment={"PATH": "/usr/bin:/bin", "HOME": "/home/arc"},
    )

    new_session = next(call for call in calls if call and call[0] == "new-session")
    shell_command = new_session[-1]
    assert shell_command.startswith("env -i ")
    assert "HOME=/home/arc" in shell_command
    assert "PATH=/usr/bin:/bin" in shell_command
    assert shell_command.endswith("python -V")
