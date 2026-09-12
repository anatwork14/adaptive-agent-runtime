from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from adapters.mock import MockAgentAdapter
from application.app import ArcApplication
from eval.runners.experiment import ExperimentRunner



def _git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# normalized baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


@pytest.mark.parametrize("baseline", ["B3", "B5", "B7"])
def test_normalized_baselines_share_transactional_execution_path(tmp_path: Path, baseline: str) -> None:
    repo = _git_repo(tmp_path / baseline)
    initial_head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
    ).strip()

    with ArcApplication(repo, f"normalized-{baseline.lower()}") as arc:
        arc.initialize()
        task = arc.create_task(
            "implement normalized baseline smoke change",
            task_id="T001",
            files=["src/normalized.py"],
            acceptance=["candidate reaches the normal ARC gate"],
            token_budget=8000,
        )
        runner = ExperimentRunner()
        summary = asyncio.run(
            runner.run_benchmark(
                arc.orchestrator,
                [task.task_id],
                MockAgentAdapter(),
                agent_id="mock",
                benchmark_id=f"normalized-{baseline}",
                baseline=baseline,
                repo_commit=initial_head,
            )
        )

        assert summary.resolved_count == 1
        assert summary.resolved_rate == pytest.approx(1.0)
        measurement = runner.last_measurements[0]
        assert measurement.baseline == baseline
        assert measurement.context_hard_budget == 8000
        assert measurement.context_tokens is not None
        assert measurement.context_tokens <= 8000
        assert measurement.retrieval_latency_ms is not None
        assert measurement.context_compile_latency_ms is not None
        assert measurement.stale_memories_delivered == 0
        assert measurement.candidate_commit_sha

        task_events = arc.event_store.read_all(project_id=arc.project_id)
        task_events = [event for event in task_events if event.task_id == task.task_id]
        kinds = [event.kind for event in task_events]
        assert "task.dispatched" in kinds
        assert "context.compiled" in kinds
        assert "context.policy_measured" in kinds
        assert "task.submitted" in kinds
        assert "gate.accepted" in kinds

        context_event = next(event for event in task_events if event.kind == "context.compiled")
        assert context_event.payload["context_policy"] == baseline
        assert context_event.payload["hard_budget"] == 8000

        policy_event = next(
            event for event in task_events if event.kind == "context.policy_measured"
        )
        assert policy_event.payload["context_policy"] == baseline
        assert policy_event.payload["retrieval_latency_ms"] >= 0.0
        assert policy_event.payload["context_compile_latency_ms"] >= 0.0

        assert (repo / "src" / "normalized.py").exists()
