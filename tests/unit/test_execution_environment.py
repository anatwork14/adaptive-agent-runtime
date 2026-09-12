"""Security regression tests for ARC-managed child-process environments."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from application.agents import build_agent
from application.config import AgentProfile
from runtime.environment import build_execution_environment, redact_command
from runtime.tmux import TmuxController, TmuxError
from runtime.tmux_bootstrap import _load_environment


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


def test_tmux_start_uses_private_environment_handoff(tmp_path, monkeypatch) -> None:
    controller = TmuxController("tmux")
    calls: list[list[str]] = []
    consumed: dict[str, object] = {}

    def fake_run(args, *, check=True, interactive=False):
        calls.append(list(args))
        if args and args[0] == "has-session":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
        if args and args[0] == "new-session":
            argv = shlex.split(args[-1])
            handoff_path = Path(argv[3])
            consumed["path"] = handoff_path
            consumed["mode"] = handoff_path.stat().st_mode & 0o777
            consumed["payload"] = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff_path.unlink()
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(controller, "_run", fake_run)
    secret = "secret-that-must-not-appear-in-tmux-argv"
    controller.start(
        name="arc-terminal-test",
        cwd=tmp_path,
        command=["python", "-V"],
        environment={"PATH": "/usr/bin:/bin", "HOME": "/home/arc", "API_KEY": secret},
    )

    new_session = next(call for call in calls if call and call[0] == "new-session")
    shell_command = new_session[-1]
    assert secret not in shell_command
    assert "API_KEY=" not in shell_command
    argv = shlex.split(shell_command)
    assert argv[1:3] == ["-m", "runtime.tmux_bootstrap"]
    assert "--" in argv
    assert consumed["mode"] == 0o600
    payload = consumed["payload"]
    assert isinstance(payload, dict)
    assert payload["API_KEY"] == secret
    assert not Path(consumed["path"]).exists()


def test_tmux_start_fails_closed_if_bootstrap_does_not_consume_handoff(
    tmp_path, monkeypatch
) -> None:
    controller = TmuxController("tmux")
    state = {"started": False, "killed": False, "handoff": None}

    def fake_run(args, *, check=True, interactive=False):
        if args and args[0] == "has-session":
            code = 0 if state["started"] and not state["killed"] else 1
            return subprocess.CompletedProcess(args, code, stdout="", stderr="")
        if args and args[0] == "new-session":
            state["started"] = True
            argv = shlex.split(args[-1])
            state["handoff"] = Path(argv[3])
        if args and args[0] == "kill-session":
            state["killed"] = True
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    ticks = iter([0.0, 10.0])
    monkeypatch.setattr(controller, "_run", fake_run)
    monkeypatch.setattr("runtime.tmux.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("runtime.tmux.time.sleep", lambda _: None)

    with pytest.raises(TmuxError, match="did not consume"):
        controller.start(
            name="arc-terminal-stalled",
            cwd=tmp_path,
            command=["python", "-V"],
            environment={"PATH": "/usr/bin:/bin", "API_KEY": "secret"},
        )

    assert state["killed"] is True
    assert isinstance(state["handoff"], Path)
    assert not state["handoff"].exists()


def test_tmux_bootstrap_deletes_handoff_after_read(tmp_path) -> None:
    handoff = tmp_path / "env.json"
    handoff.write_text(json.dumps({"PATH": "/usr/bin", "TOKEN": "secret"}), encoding="utf-8")
    environment = _load_environment(handoff)
    assert environment == {"PATH": "/usr/bin", "TOKEN": "secret"}
    assert not handoff.exists()
