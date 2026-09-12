from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from adapters.base import AgentRunResult
from adapters.mock import MockAgentAdapter
from application.app import ArcApplication
from eval.runners.experiment import ExperimentRunner


def _git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "arc@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "ARC Test"],
        check=True,
    )
    (repo / "README.md").write_text("# normalized baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


@pytest.mark.parametrize("baseline", ["B3", "B5", "B7"])
def test_normalized_baselines_share_transactional_execution_path(
    tmp_path: Path, baseline: str
) -> None:
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
        assert measurement.context_policy == baseline
        assert measurement.context_hard_budget == 8000
        assert measurement.context_tokens is not None
        assert measurement.context_tokens <= 8000
        assert measurement.retrieval_latency_ms is not None
        assert measurement.context_compile_latency_ms is not None
        assert measurement.stale_memories_delivered == 0
        assert measurement.stale_memory_ids == []
        assert measurement.candidate_commit_sha
        assert measurement.retrieval_strategies

        if baseline == "B3":
            assert measurement.retrieval_strategies == ["static_no_memory"]
        elif baseline == "B5":
            assert measurement.retrieval_strategies == ["naive_vector_topk:k=5"]

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


@pytest.mark.parametrize(
    ("baseline", "expects_summary_memory"),
    [("B3", False), ("B5", True), ("B7", True)],
)
def test_successful_prior_task_summary_reaches_later_context(
    tmp_path: Path,
    baseline: str,
    expects_summary_memory: bool,
) -> None:
    repo = _git_repo(tmp_path / f"summary-{baseline}")
    initial_head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    captured = {}

    def handler(context, workspace):
        captured[context.task_id] = context
        target = workspace / f"{context.task_id.lower()}.txt"
        target.write_text(f"implemented {context.goal}\n", encoding="utf-8")
        return AgentRunResult(
            status="completed",
            patch_ref="WORKTREE",
            diff="",
            summary=f"implemented {context.task_id}: shared parser abstraction",
            memory_references=list(context.memory_ids),
            decisions=[],
            assumptions=[],
            token_usage={
                "prompt_tokens": context.context_token_count,
                "completion_tokens": 16,
            },
            cost_usd=0.0,
        )

    with ArcApplication(repo, f"summary-{baseline.lower()}") as arc:
        arc.initialize()
        first = arc.create_task(
            "introduce shared parser abstraction",
            task_id="T001",
            files=["t001.txt"],
            acceptance=["shared parser abstraction exists"],
            token_budget=8000,
        )
        second = arc.create_task(
            "extend shared parser abstraction",
            task_id="T002",
            dependencies=["T001"],
            files=["t002.txt"],
            acceptance=["extension reuses the earlier abstraction"],
            token_budget=8000,
        )
        runner = ExperimentRunner()
        summary = asyncio.run(
            runner.run_benchmark(
                arc.orchestrator,
                [first.task_id, second.task_id],
                MockAgentAdapter(handler=handler),
                agent_id="mock",
                benchmark_id=f"summary-memory-{baseline}",
                baseline=baseline,
                repo_commit=initial_head,
            )
        )

    assert summary.resolved_count == 2
    later = captured["T002"]
    if expects_summary_memory:
        assert later.episodes
        assert later.memory_ids
        assert any("T001" in item["text"] for item in later.episodes)
        assert any("shared parser abstraction" in item["text"] for item in later.episodes)
    else:
        assert later.episodes == []
        assert later.memory_ids == []
