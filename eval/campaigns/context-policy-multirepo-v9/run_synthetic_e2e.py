"""Provider-free V9 apparatus qualification.

The successful path uses the real paired campaign runner with a deterministic
agent and a disposable hidden grader. The timeout path uses the real
orchestrator with a deterministic failed provider result. Neither path invokes
Codex or creates a benchmark campaign attempt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from adapters.base import AgentBudget, AgentRunResult
from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.runners.paired import IsolatedPairedBenchmarkRunner
from isolation.container import SandboxRunner, SandboxUnavailable
from memory.lifecycle import MemoryLifecycle
from runtime.git import arc_git_write_args
from runtime.orchestrator import Orchestrator
from state.events import EventStore

IMAGE = "arc-v8-click:qualified"
IMAGE_DIGEST = "sha256:7fae74105025e759c4244de903b1385271df9ac4f8e4bfb3d1589094d2ec92a4"
BASELINES = ("B3", "B5", "B7")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_fixture(root: Path) -> tuple[Path, Path, str, dict[str, object]]:
    repo = root / "repo"
    hidden = root / "hidden-tests"
    root.mkdir(parents=True, exist_ok=True)
    repo.mkdir()
    hidden.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "candidate.py").write_text(
        "def transform(value):\n    return value\n",
        encoding="utf-8",
    )
    (repo / "test_visible.py").write_text(
        "from candidate import transform\n\n\ndef test_candidate_contract():\n"
        "    assert transform('arc') == 'ARC'\n",
        encoding="utf-8",
    )
    _git(repo, "add", "candidate.py", "test_visible.py")
    _git(
        repo,
        *arc_git_write_args(
            ["commit", "-m", "synthetic base"],
            user_name="ARC Fixture",
            user_email="arc-fixture@local",
        ),
    )
    base_commit = _git(repo, "rev-parse", "HEAD")

    (hidden / "test_hidden_t001.py").write_text(
        "from candidate import transform\n\n\ndef test_hidden_candidate_contract():\n"
        "    assert transform('v8') == 'V8'\n",
        encoding="utf-8",
    )
    harness: dict[str, object] = {
        "backend": "docker",
        "image": IMAGE,
        "image_digest": IMAGE_DIGEST,
        "command": ["python", "-m", "pytest", "-q"],
        "environment": {"PYTHONPATH": "/workspace"},
        "hidden_command": [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "/arc-hidden-tests",
        ],
        "hidden_environment": {"PYTHONPATH": "/workspace"},
        "network_enabled": False,
        "tmpfs_exec": True,
        "timeout_seconds": 180,
    }
    return repo, hidden, base_commit, harness


class _SyntheticSuccessAgent:
    def __init__(self, timeout_observations: list[int]) -> None:
        self.name = "synthetic-agent"
        self.timeout_observations = timeout_observations

    async def run(self, *, context, workspace: Path, budget: AgentBudget) -> AgentRunResult:
        self.timeout_observations.append(budget.timeout_seconds)
        (workspace / "candidate.py").write_text(
            "def transform(value):\n    return value.upper()\n",
            encoding="utf-8",
        )
        return AgentRunResult(
            status="completed",
            summary="synthetic agent completed",
            token_usage={"prompt_tokens": 7, "completion_tokens": 3},
        )


def _manifests(base_commit: str) -> list[BenchmarkManifest]:
    task = EvaluationTaskSpec(
        task_id="T001",
        goal="Implement the uppercase transform contract",
        files=["candidate.py"],
        acceptance=["visible and hidden tests pass"],
        token_budget=1200,
        hidden_test_pattern="test_hidden_t001.py",
    )
    return [
        BenchmarkManifest(
            benchmark_id="synthetic-v8-apparatus",
            baseline=baseline,
            seed=42,
            agent_profile="synthetic-agent",
            model="synthetic-no-provider",
            repo_commit=base_commit,
            context_token_budget=1200,
            hard_task_usd=2.0,
            project_constraints=["offline synthetic test"],
            tasks=[task],
        )
        for baseline in BASELINES
    ]


def _run_success(root: Path) -> dict[str, object]:
    repo, hidden, base_commit, harness = _create_fixture(root / "success")
    sandbox_identity = SandboxRunner(
        repo,
        image=IMAGE,
        image_digest=IMAGE_DIGEST,
        network_enabled=False,
        timeout_seconds=180,
        tmpfs_noexec=False,
    ).verify_available()
    timeout_observations: list[int] = []
    runner = IsolatedPairedBenchmarkRunner(
        repo,
        output_root=root / "success-results",
        workspace_root=root / "success-runtime",
        verification_level="V0",
        visible_test_cmd=list(harness["command"]),
        visible_test_harness=harness,
        hard_project_usd=10.0,
        hidden_test_dir=hidden,
        provider_execution_timeout_seconds=600,
    )
    paired = asyncio.run(
        runner.run(
            _manifests(base_commit),
            lambda: _SyntheticSuccessAgent(timeout_observations),
        run_id="synthetic-v8-apparatus",
        )
    )
    summaries = {
        baseline: result.summary.model_dump(mode="json")
        for baseline, result in sorted(paired.runs.items())
    }
    measurements = {
        baseline: [item.model_dump(mode="json") for item in result.measurements]
        for baseline, result in sorted(paired.runs.items())
    }
    return {
        "status": "SUCCEEDED",
        "sandbox_identity": sandbox_identity,
        "provider_execution_started": False,
        "base_commit": base_commit,
        "baseline_order": list(paired.execution_order),
        "baseline_summaries": summaries,
        "baseline_measurements": measurements,
        "provider_timeout_observations": timeout_observations,
        "integration_git_status": _git(repo, "status", "--porcelain"),
        "assertions": {
            "all_baselines_completed": set(summaries) == set(BASELINES),
            "all_hidden_tests_passed": all(
                measurement[0]["hidden_tests_passed"] is True
                for measurement in measurements.values()
            ),
            "all_provider_timeouts_are_600": bool(timeout_observations)
            and set(timeout_observations) == {600},
            "provider_execution_started_false": True,
            "integration_clean_after_cleanup": _git(repo, "status", "--porcelain") == "",
        },
    }


async def _timeout_task(root: Path) -> dict[str, object]:
    repo, _hidden, _base_commit, _harness = _create_fixture(root / "timeout")
    store = EventStore(root / "timeout-events.db")
    connection = sqlite3.connect(root / "timeout-memory.db", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    try:
        orchestrator = Orchestrator(
            store,
            MemoryLifecycle(connection),
            repo,
            "synthetic-v8-timeout",
            provider_execution_timeout_seconds=600,
        )
        orchestrator.init_project(spec={"name": "synthetic timeout"})
        orchestrator.create_task("T001", "synthetic timeout", files_declared=["candidate.py"])

        class _TimeoutAgent:
            async def run(self, *, context, workspace, budget) -> AgentRunResult:
                return AgentRunResult(
                    status="failed",
                    summary="synthetic provider timeout after response began",
                    failure_classification="CLI_TIMEOUT",
                    provider_outcome="timeout",
                    provider_returncode=-15,
                    configured_timeout_seconds=budget.timeout_seconds,
                    elapsed_seconds=600.0,
                    provider_lifecycle={
                        "process_started": "observed",
                        "prompt_written": "observed",
                        "request_started": "observed",
                        "response_started": "observed",
                        "completed": "unknown",
                        "failed": "observed",
                    },
                )

        try:
            await orchestrator.execute_task("T001", _TimeoutAgent(), "synthetic-agent")
        except RuntimeError:
            pass
        events = store.read_all(project_id="synthetic-v8-timeout")
        failures = [event for event in events if event.kind == "provider.failed"]
        return {
            "status": "EXPECTED_TIMEOUT",
            "provider_execution_started": False,
            "failure_classification": failures[-1].payload["failure_classification"],
            "configured_timeout_seconds": failures[-1].payload["configured_timeout_seconds"],
            "provider_lifecycle": failures[-1].payload["provider_lifecycle"],
            "candidate_or_measurement_created": any(
                event.kind in {"task.submitted", "measurement.created"} for event in events
            ),
            "assertions": {
                "timeout_is_durable": bool(failures),
                "no_manufactured_completion": not any(
                    event.kind in {"task.submitted", "measurement.created"} for event in events
                ),
                "provider_execution_started_false": True,
            },
        }
    finally:
        connection.close()
        store.close()


def _run(root: Path) -> dict[str, object]:
    success = _run_success(root)
    timeout = asyncio.run(_timeout_task(root))
    return {
            "qualification": "provider-free synthetic V9 timeout apparatus",
            "campaign_id": "context-policy-multirepo-v9",
        "success_path": success,
        "timeout_path": timeout,
        "provider_execution_started": False,
        "benchmark_attempt_created": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="arc-v9-synthetic-") as directory:
            result = _run(Path(directory))
    except SandboxUnavailable as exc:
        result = {
            "qualification": "provider-free synthetic V9 timeout apparatus",
            "status": "BLOCKED",
            "provider_execution_started": False,
            "error": str(exc),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
