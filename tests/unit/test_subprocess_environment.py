"""Direct subprocess-boundary tests for ARC's least-privilege environment."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from adapters.base import AgentBudget
from adapters.cli_process import SubprocessCodingAgent


class _FakeStdin:
    def __init__(self) -> None:
        self.payload = b""

    def write(self, payload: bytes) -> None:
        self.payload += payload

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode = 0
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(b"completed\n")
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


def test_subprocess_agent_passes_explicit_least_privilege_environment(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs["env"])
        process = _FakeProcess()
        captured["process"] = process
        return process

    monkeypatch.setattr(
        "adapters.cli_process.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "other-provider-key")
    monkeypatch.setenv("DATABASE_PASSWORD", "must-not-leak")
    monkeypatch.setenv("ARC_TEST_EXTRA", "explicit-extra")

    agent = SubprocessCodingAgent(
        name="test-codex",
        executable=sys.executable,
        command=[sys.executable, "--version"],
        provider="codex",
        env_allow=["ARC_TEST_EXTRA"],
    )
    result = asyncio.run(
        agent.run_prompt(
            prompt="test prompt",
            workspace=tmp_path,
            budget=AgentBudget(max_usd=1.0, max_tokens=1000),
        )
    )

    assert result.status == "completed"
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["OPENAI_API_KEY"] == "provider-key"
    assert environment["ARC_TEST_EXTRA"] == "explicit-extra"
    assert "ANTHROPIC_API_KEY" not in environment
    assert "DATABASE_PASSWORD" not in environment
    process = captured["process"]
    assert isinstance(process, _FakeProcess)
    assert process.stdin.payload == b"test prompt"
    trace = result.tool_trace[0]
    assert "OPENAI_API_KEY" in trace["environment_keys"]
    assert "ANTHROPIC_API_KEY" not in trace["environment_keys"]
