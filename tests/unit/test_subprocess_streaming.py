"""Deterministic coverage for live provider-turn streaming and cancellation."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from adapters.base import AgentBudget
from adapters.cli_process import SubprocessCodingAgent


@pytest.mark.asyncio
async def test_provider_output_streams_before_process_exit_and_redacts_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-arc-super-secret-123456789"
    monkeypatch.setenv("ARC_TEST_API_KEY", secret)
    code = (
        "import os,sys,time; "
        "sys.stdin.read(); "
        "print('first-line', flush=True); "
        "time.sleep(0.4); "
        "print('secret=' + os.environ['ARC_TEST_API_KEY'], flush=True); "
        "print('stderr=' + os.environ['ARC_TEST_API_KEY'], file=sys.stderr, flush=True)"
    )
    agent = SubprocessCodingAgent(
        name="stream-test",
        executable=sys.executable,
        command=[sys.executable, "-c", code],
        provider=None,
        env_allow=["ARC_TEST_API_KEY"],
    )
    chunks: list[tuple[str, str]] = []
    first_seen = asyncio.Event()

    async def capture(stream: str, text: str) -> None:
        chunks.append((stream, text))
        if "first-line" in text:
            first_seen.set()

    task = asyncio.create_task(
        agent.run_prompt(
            prompt="do work",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=5),
            output_callback=capture,
        )
    )
    await asyncio.wait_for(first_seen.wait(), timeout=2)
    assert not task.done(), "the first output line must arrive before the provider process exits"

    result = await task
    assert result.status == "completed"
    rendered = "".join(text for _, text in chunks) + result.summary
    assert secret not in rendered
    assert "<redacted>" in rendered
    assert any(stream == "stderr" for stream, _ in chunks)


@pytest.mark.asyncio
async def test_provider_turn_can_be_cancelled_without_waiting_for_timeout(tmp_path: Path) -> None:
    code = (
        "import sys,time; "
        "sys.stdin.read(); "
        "print('provider-started', flush=True); "
        "time.sleep(30)"
    )
    agent = SubprocessCodingAgent(
        name="cancel-test",
        executable=sys.executable,
        command=[sys.executable, "-c", code],
        provider=None,
    )
    cancel = asyncio.Event()
    started = asyncio.Event()

    async def capture(stream: str, text: str) -> None:
        if stream == "stdout" and "provider-started" in text:
            started.set()

    task = asyncio.create_task(
        agent.run_prompt(
            prompt="do long work",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=40),
            output_callback=capture,
            cancel_event=cancel,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    cancel.set()
    result = await asyncio.wait_for(task, timeout=4)

    assert result.status == "cancelled"
    assert "cancelled" in result.summary.lower()
    assert result.tool_trace[-1]["action"] == "cli_cancelled"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group semantics")
async def test_provider_cancellation_terminates_descendant_processes(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-survived.txt"
    child_code = (
        "import pathlib,time; "
        "time.sleep(1.0); "
        f"pathlib.Path({str(marker)!r}).write_text('alive', encoding='utf-8')"
    )
    provider_code = (
        "import subprocess,sys,time; "
        "sys.stdin.read(); "
        f"subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}]); "
        "print('child-started', flush=True); "
        "time.sleep(30)"
    )
    agent = SubprocessCodingAgent(
        name="tree-cancel-test",
        executable=sys.executable,
        command=[sys.executable, "-c", provider_code],
        provider=None,
    )
    cancel = asyncio.Event()
    child_started = asyncio.Event()

    async def capture(stream: str, text: str) -> None:
        if stream == "stdout" and "child-started" in text:
            child_started.set()

    task = asyncio.create_task(
        agent.run_prompt(
            prompt="spawn child",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=40),
            output_callback=capture,
            cancel_event=cancel,
        )
    )
    await asyncio.wait_for(child_started.wait(), timeout=2)
    cancel.set()
    result = await asyncio.wait_for(task, timeout=4)
    assert result.status == "cancelled"

    # If ARC killed only the provider parent, the inherited child would still
    # write this marker after cancellation. The whole supervised process group
    # must be gone before the turn lock can be released.
    await asyncio.sleep(1.2)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_pre_cancelled_turn_never_launches_provider(tmp_path: Path) -> None:
    cancel = asyncio.Event()
    cancel.set()
    agent = SubprocessCodingAgent(
        name="pre-cancel-test",
        executable=sys.executable,
        command=[sys.executable, "-c", "raise SystemExit(99)"],
        provider=None,
    )

    result = await agent.run_prompt(
        prompt="should not launch",
        workspace=tmp_path,
        budget=AgentBudget(timeout_seconds=5),
        cancel_event=cancel,
    )

    assert result.status == "cancelled"
    assert result.tool_trace[-1]["phase"] == "pre_launch"
