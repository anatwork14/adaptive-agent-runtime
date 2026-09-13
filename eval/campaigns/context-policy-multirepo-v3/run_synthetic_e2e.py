"""Run the provider-free post-provider ARC apparatus qualification.

This uses a disposable synthetic repository and synthetic hidden grader. It is
not a benchmark campaign and never invokes a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from adapters.base import AgentRunResult
from adapters.mock import MockAgentAdapter
from eval.grading.hidden_tests import HiddenTestGrader
from eval.io import write_measurements_jsonl, write_summary_json
from eval.models import BenchmarkManifest, EvaluationSummary, EvaluationTaskSpec, TaskMeasurement
from eval.runners.experiment import ExperimentRunner
from isolation.container import SandboxRunner, SandboxUnavailable
from memory.lifecycle import MemoryLifecycle
from runtime.git import arc_git_write_args
from runtime.orchestrator import Orchestrator
from state.events import EventStore

IMAGE = "arc-v2-click:qualified"
IMAGE_DIGEST = "sha256:7fae74105025e759c4244de903b1385271df9ac4f8e4bfb3d1589094d2ec92a4"


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
        "    assert transform('v3') == 'V3'\n",
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


def _run(root: Path) -> dict[str, object]:
    repo, hidden, base_commit, harness = _create_fixture(root)
    sandbox = SandboxRunner(
        repo,
        image=IMAGE,
        image_digest=IMAGE_DIGEST,
        network_enabled=False,
        tmpfs_noexec=False,
    )
    sandbox_identity = sandbox.verify_available()

    event_store = EventStore(root / "events.db")
    memory_connection = sqlite3.connect(root / "memory.db", check_same_thread=False)
    try:
        project_id = "synthetic-v3-apparatus"
        orchestrator = Orchestrator(
            event_store,
            MemoryLifecycle(memory_connection),
            repo,
            project_id,
            verification_level="V0",
            hard_task_usd=2.0,
            hard_project_usd=10.0,
            visible_test_harness=harness,
        )
        orchestrator.init_project(spec={"name": project_id}, constraints=["offline synthetic test"])
        orchestrator.create_task(
            task_id="T001",
            goal="Implement the uppercase transform contract",
            files_declared=["candidate.py"],
            acceptance_criteria=["visible and hidden tests pass"],
            token_budget=1200,
        )

        def handler(_context, workspace: Path) -> AgentRunResult:
            (workspace / "candidate.py").write_text(
                "def transform(value):\n    return value.upper()\n",
                encoding="utf-8",
            )
            return AgentRunResult(
                status="completed",
                summary="synthetic agent completed",
                token_usage={"prompt_tokens": 7, "completion_tokens": 3},
            )

        manifest = BenchmarkManifest(
            benchmark_id="synthetic-v3-apparatus",
            baseline="B7",
            agent_profile="synthetic-agent",
            model="synthetic-no-provider",
            repo_commit=base_commit,
            context_token_budget=1200,
            hard_task_usd=2.0,
            project_constraints=["offline synthetic test"],
            tasks=[
                EvaluationTaskSpec(
                    task_id="T001",
                    goal="Implement the uppercase transform contract",
                    files=["candidate.py"],
                    acceptance=["visible and hidden tests pass"],
                    token_budget=1200,
                    hidden_test_pattern="test_hidden_t001.py",
                )
            ],
        )
        runner = ExperimentRunner(HiddenTestGrader(hidden, harness=harness))
        summary = asyncio.run(
            runner.run_manifest(
                orchestrator,
                manifest,
                MockAgentAdapter(name="synthetic-agent", handler=handler),
            )
        )
        measurements = list(runner.last_measurements)
        events = event_store.read_all(project_id=project_id)
        event_kinds = [event.kind for event in events]
        projection = orchestrator.get_projection()
        candidate_sha = measurements[0].candidate_commit_sha
        if not candidate_sha:
            raise RuntimeError("synthetic run did not persist a candidate commit")
        status = _git(repo, "status", "--porcelain")
        return {
            "qualification": "provider-free synthetic end-to-end apparatus",
            "provider_execution_started": False,
            "sandbox_identity": sandbox_identity,
            "workflow": [
                "context compile",
                "fake successful agent",
                "candidate commit",
                "IntegrationGate",
                "visible Docker G2",
                "integration",
                "task-scoped hidden Docker grading",
                "durable measurement",
                "task completion",
            ],
            "base_commit": base_commit,
            "candidate_commit": candidate_sha,
            "summary": summary.model_dump(mode="json"),
            "measurement": measurements[0].model_dump(mode="json"),
            "event_kinds": event_kinds,
            "task_projection_status": projection.dag.tasks["T001"].status.value,
            "gate_accepted": "gate.accepted" in event_kinds,
            "visible_docker_g2": "G2_visible_tests" in (
                next(
                    event.payload.get("stages_passed", [])
                    for event in events
                    if event.kind == "gate.accepted"
                )
            ),
            "hidden_docker_passed": measurements[0].hidden_tests_passed is True,
            "measurement_durable": bool(measurements[0].event_end >= measurements[0].event_start),
            "integration_git_status": status,
            "integration_clean_after_cleanup": status == "",
            "assertions": {
                "resolved_count": summary.resolved_count == 1,
                "gate_status": measurements[0].gate_status == "accepted",
                "hidden_tests_passed": measurements[0].hidden_tests_passed is True,
                "provider_execution_started_false": True,
            },
        }
    finally:
        memory_connection.close()
        event_store.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="arc-v3-synthetic-") as directory:
            result = _run(Path(directory))
    except SandboxUnavailable as exc:
        result = {"qualification": "provider-free synthetic end-to-end apparatus", "status": "BLOCKED", "error": str(exc)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_measurements_jsonl(
        args.output.with_name("synthetic-measurements.jsonl"),
        [TaskMeasurement.model_validate(result["measurement"])],
    )
    write_summary_json(
        args.output.with_name("synthetic-summary.json"),
        EvaluationSummary.model_validate(result["summary"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
