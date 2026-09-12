"""Deterministic provider diagnostics and durable failure evidence tests."""

from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from adapters.base import AgentBudget, AgentRunResult, classify_provider_failure
from adapters.cli_process import SubprocessCodingAgent
from adapters.codex import CodexAgentAdapter
from application.config import AgentProfile
from application.provider_doctor import run_provider_probe
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore


def _run(code: str, tmp_path: Path, *, timeout: int = 5) -> AgentRunResult:
    agent = SubprocessCodingAgent(
        name="fake-provider",
        executable=sys.executable,
        command=[sys.executable, "-c", code],
        provider="codex",
    )
    return asyncio.run(
        agent.run_prompt(
            prompt="synthetic probe",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=timeout),
        )
    )


def test_missing_cli_is_classified_without_raising(tmp_path: Path) -> None:
    agent = SubprocessCodingAgent(
        name="missing-provider",
        executable="definitely-not-installed-arc-provider",
        provider="codex",
    )

    result = asyncio.run(
        agent.run_prompt(
            prompt="synthetic probe",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=5),
        )
    )

    assert result.status == "failed"
    assert result.failure_classification == "CLI_NOT_FOUND"
    assert result.provider_returncode is None
    assert result.provider_outcome == "not_found"
    assert result.provider_lifecycle["process_started"] == "unknown"
    assert result.provider_lifecycle["failed"] == "observed"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"status": "failed", "outcome": "timeout"}, "CLI_TIMEOUT"),
        ({"status": "cancelled", "outcome": "cancelled"}, "CLI_CANCELLED"),
        ({"status": "failed", "summary": "authentication required"}, "AUTH_FAILURE"),
        ({"status": "failed", "summary": "HTTP 503 service unavailable"}, "PROVIDER_SERVICE_ERROR"),
        ({"status": "failed", "summary": "connection refused"}, "NETWORK_ERROR"),
        ({"status": "failed", "summary": "unsupported model"}, "CONFIGURATION_ERROR"),
        ({"status": "failed"}, "UNKNOWN_PROVIDER_FAILURE"),
    ],
)
def test_failure_classifier_preserves_unknown_cases(kwargs: dict, expected: str) -> None:
    assert classify_provider_failure(**kwargs) == expected


@pytest.mark.parametrize("returncode", [1, 2])
def test_cli_nonzero_exit_persists_returncode_and_stderr(returncode: int, tmp_path: Path) -> None:
    code = (
        "import sys; sys.stdin.read(); "
        "print('synthetic provider failure', file=sys.stderr, flush=True); "
        f"raise SystemExit({returncode})"
    )
    result = _run(code, tmp_path)

    assert result.status == "failed"
    assert result.failure_classification == "CLI_NONZERO_EXIT"
    assert result.provider_returncode == returncode
    assert result.provider_outcome == "failed"
    assert "synthetic provider failure" in result.stderr_tail
    assert result.tool_trace[-1]["returncode"] == returncode
    assert result.provider_lifecycle["process_started"] == "observed"
    assert result.provider_lifecycle["request_started"] == "unknown"
    assert result.provider_lifecycle["prompt_written"] == "observed"
    assert result.provider_lifecycle["failed"] == "observed"
    assert len(result.stdout_tail) <= 8000
    assert len(result.stderr_tail) <= 4000


def test_secret_in_provider_output_is_redacted_in_result(tmp_path: Path, monkeypatch) -> None:
    secret = "sk-arc-diagnostic-secret-123456789"
    monkeypatch.setenv("ARC_TEST_API_KEY", secret)
    code = (
        "import os,sys; sys.stdin.read(); "
        "print(os.environ['ARC_TEST_API_KEY'], file=sys.stderr, flush=True); "
        "raise SystemExit(17)"
    )
    agent = SubprocessCodingAgent(
        name="secret-provider",
        executable=sys.executable,
        command=[sys.executable, "-c", code],
        provider="codex",
        env_allow=["ARC_TEST_API_KEY"],
    )
    result = asyncio.run(
        agent.run_prompt(
            prompt="synthetic probe",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=5),
        )
    )

    assert result.status == "failed"
    assert result.provider_returncode == 17
    assert secret not in result.summary
    assert secret not in result.stderr_tail
    assert "<redacted>" in result.stderr_tail


def test_timeout_and_empty_output_are_distinguishable(tmp_path: Path) -> None:
    timeout_result = _run(
        "import sys,time; sys.stdin.read(); time.sleep(30)",
        tmp_path,
        timeout=1,
    )
    empty_result = _run("import sys; sys.stdin.read()", tmp_path)

    assert timeout_result.status == "failed"
    assert timeout_result.failure_classification == "CLI_TIMEOUT"
    assert timeout_result.provider_outcome == "timeout"
    assert timeout_result.provider_lifecycle["failed"] == "observed"
    assert empty_result.status == "completed"
    assert empty_result.provider_outcome == "completed"
    assert empty_result.stdout_tail == ""
    assert empty_result.provider_lifecycle["response_started"] == "unknown"
    assert empty_result.provider_lifecycle["completed"] == "observed"


def test_process_can_exit_after_prompt_before_provider_request_boundary(tmp_path: Path) -> None:
    result = _run("import sys; sys.stdin.read(); raise SystemExit(17)", tmp_path)

    assert result.provider_lifecycle["process_started"] == "observed"
    assert result.provider_lifecycle["prompt_written"] == "observed"
    assert result.provider_lifecycle["request_started"] == "unknown"
    assert result.provider_lifecycle["response_started"] == "unknown"
    assert result.provider_lifecycle["failed"] == "observed"
    assert result.failure_classification == "CLI_NONZERO_EXIT"


def test_codex_jsonl_exit_zero_without_lifecycle_completion_fails_closed(tmp_path: Path) -> None:
    script = tmp_path / "codex-no-turn.py"
    script.write_text(
        "import sys; sys.stdin.read(); print('plain output', flush=True)\n",
        encoding="utf-8",
    )
    command = shlex.join([sys.executable, str(script), "--json"])
    result = asyncio.run(
        CodexAgentAdapter(command_override=command).run_prompt(
            prompt="synthetic probe",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=5),
        )
    )

    assert result.status == "failed"
    assert result.failure_classification == "UNKNOWN_PROVIDER_FAILURE"
    assert result.provider_outcome == "incomplete_structured_turn"
    assert result.provider_returncode == 0
    assert result.provider_lifecycle["process_started"] == "observed"
    assert result.provider_lifecycle["prompt_written"] == "observed"
    assert result.provider_lifecycle["request_started"] == "unknown"
    assert result.provider_lifecycle["completed"] == "unknown"
    assert result.provider_lifecycle["failed"] == "observed"


def test_codex_jsonl_fixture_maps_only_observable_lifecycle_events() -> None:
    adapter = CodexAgentAdapter()
    assert adapter.parse_output_events("stdout", '{"type":"turn.started"}\n') == [
        "provider.request_started"
    ]
    assert adapter.parse_output_events(
        "stdout", '{"type":"item.started","item":{"type":"agent_message"}}\n'
    ) == ["provider.response_started"]
    assert adapter.parse_output_events(
        "stdout", '{"type":"item.completed","item":{"type":"agent_message"}}\n'
    ) == ["provider.response_started"]
    assert adapter.parse_output_events("stdout", '{"type":"turn.completed"}\n') == [
        "provider.completed"
    ]
    assert adapter.parse_output_events("stdout", '{"type":"error"}\n') == ["provider.failed"]
    assert adapter.parse_output_events("stdout", "not-json\n") == []


def test_codex_jsonl_usage_maps_without_double_counting() -> None:
    adapter = CodexAgentAdapter()
    usage = adapter.parse_output_metadata(
        "stdout",
        '{"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":7,"cached_input_tokens":3,"reasoning_output_tokens":2}}\n',
    )

    assert usage == {
        "token_usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "cached_prompt_tokens": 3,
            "reasoning_tokens": 2,
        }
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ('{"type":"error"}', "UNKNOWN_PROVIDER_FAILURE"),
        ('{"type":"error","message":"HTTP 503 service unavailable"}', "PROVIDER_SERVICE_ERROR"),
    ],
)
def test_codex_structured_error_classification_is_conservative(
    tmp_path: Path, payload: str, expected: str
) -> None:
    script = tmp_path / "codex-error.py"
    event = json.loads(payload)
    script.write_text(
        f"import json, sys; sys.stdin.read(); print(json.dumps({event!r}), flush=True)\n",
        encoding="utf-8",
    )
    result = asyncio.run(
        CodexAgentAdapter(command_override=shlex.join([sys.executable, str(script)])).run_prompt(
            prompt="synthetic probe",
            workspace=tmp_path,
            budget=AgentBudget(timeout_seconds=5),
        )
    )

    assert result.status == "failed"
    assert result.failure_classification == expected


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True)
    (repo / "README.md").write_text("# diagnostics\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


class _FailingAdapter:
    async def run(self, *, context, workspace, budget) -> AgentRunResult:
        return AgentRunResult(
            status="failed",
            summary="synthetic diagnostic sk-arc-secret-123456789",
            tool_trace=[
                {
                    "action": "cli_run",
                    "returncode": 17,
                    "command": ["provider", "--api-key", "sk-arc-secret-123456789"],
                    "environment": {"API_KEY": "sk-arc-secret-123456789"},
                }
            ],
            token_usage={"prompt_tokens": 0},
            cost_usd=0.0,
        )


@pytest.mark.asyncio
async def test_orchestrator_persists_v1_failure_diagnostics_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    store = EventStore(tmp_path / "state.db")
    memory = MemoryLifecycle(sqlite3_connect(tmp_path / "memory.db"))
    orchestrator = Orchestrator(store, memory, repo, "diagnostic-project")
    orchestrator.init_project(spec={"name": "diagnostics"})
    orchestrator.create_task("T001", "synthetic failure", files_declared=["README.md"])

    with pytest.raises(RuntimeError, match="did not complete task T001"):
        await orchestrator.execute_task("T001", _FailingAdapter(), "builder")

    events = store.read_all(project_id="diagnostic-project")
    provider_failed = next(event for event in events if event.kind == "provider.failed")
    task_failed = next(event for event in events if event.kind == "task.failed")
    for event in (provider_failed, task_failed):
        payload = event.payload
        assert payload["agent_status"] == "failed"
        assert payload["agent_summary"] == "synthetic diagnostic <redacted>"
        assert payload["provider_returncode"] == 17
        assert payload["failure_classification"] == "CLI_NONZERO_EXIT"
        assert payload["tool_trace"][0]["returncode"] == 17
        assert payload["tool_trace"][0]["command"][-1] == "<redacted>"
        assert "sk-arc-secret-123456789" not in json.dumps(payload)


def sqlite3_connect(path: Path):
    import sqlite3

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def test_active_probe_isolated_and_non_scientific(tmp_path: Path) -> None:
    script = tmp_path / "provider.py"
    script.write_text(
        "import sys; sys.stdin.read(); print('ARC_PROVIDER_SMOKE_OK', flush=True)\n",
        encoding="utf-8",
    )
    profile = AgentProfile(
        name="builder",
        provider="codex",
        model="synthetic-model",
        command_override=shlex.join([sys.executable, str(script)]),
    )
    output = tmp_path / "probe.json"

    report = run_provider_probe(profile, output_path=output)

    assert report["active"]["success"] is True
    assert report["benchmark_context"] is False
    assert report["scientific_evidence"] is False
    assert report["active"]["workspace_disposable"] is True
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema"] == "arc-provider-probe-v1"
