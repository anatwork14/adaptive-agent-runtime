"""Direct subprocess-boundary tests for ARC's least-privilege environment."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from adapters.base import AgentBudget
from adapters.cli_process import SubprocessCodingAgent


class _FakeProcess:
    returncode = 0

    async def communicate(self, payload: bytes):
        self.payload = payload
        return b"completed", b""

    def kill(self) -> None:
        return None

    async def wait(self) -> int:
        return 0


def test_subprocess_agent_passes_explicit_least_privilege_environment(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs["env"])
        return _FakeProcess()

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
    trace = result.tool_trace[0]
    assert "OPENAI_API_KEY" in trace["environment_keys"]
    assert "ANTHROPIC_API_KEY" not in trace["environment_keys"]
