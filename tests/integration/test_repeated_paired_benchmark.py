from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from adapters.base import AgentRunResult
from adapters.mock import MockAgentAdapter
from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.runners.repeated import RepeatedPairedBenchmarkRunner


def _git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "shared.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, sha


def _manifests(repo_sha: str) -> list[BenchmarkManifest]:
    tasks = [
        EvaluationTaskSpec(
            task_id="T001",
            goal="Establish parser compatibility contract",
            files=["shared.txt"],
            acceptance=["candidate integrates"],
            token_budget=4000,
        ),
        EvaluationTaskSpec(
            task_id="T002",
            goal="Extend parser compatibility contract",
            dependencies=["T001"],
            files=["shared.txt"],
            acceptance=["candidate integrates"],
            token_budget=4000,
        ),
    ]
    return [
        BenchmarkManifest(
            benchmark_id="repeated-smoke",
            baseline=baseline,
            seed=17,
            agent_profile="mock",
            model=None,
            repo_commit=repo_sha,
            context_token_budget=4000,
            hard_task_usd=1.0,
            project_constraints=["offline"],
            tasks=[task.model_copy(deep=True) for task in tasks],
        )
        for baseline in ("B3", "B5", "B7")
    ]


def _factory(counter: list[int]):
    def build() -> MockAgentAdapter:
        counter.append(1)

        def handler(context, workspace: Path) -> AgentRunResult:
            target = workspace / "shared.txt"
            target.write_text(
                target.read_text(encoding="utf-8") + f"{context.task_id}\n",
                encoding="utf-8",
            )
            return AgentRunResult(
                status="completed",
                patch_ref="WORKTREE",
                summary=f"completed {context.task_id}",
                decisions=[
                    {
                        "decision": "preserve parser compatibility contract",
                        "confidence": 1.0,
                    }
                ],
                token_usage={"prompt_tokens": 100, "completion_tokens": 10},
                cost_usd=0.0,
            )

        return MockAgentAdapter(name="mock", handler=handler)

    return build


def test_repeated_triplets_preserve_isolation_and_emit_aggregate_provenance(
    tmp_path: Path,
) -> None:
    repo, base_sha = _git_repo(tmp_path)
    created_agents: list[int] = []
    runner = RepeatedPairedBenchmarkRunner(
        repo,
        output_root=tmp_path / "results",
        workspace_root=tmp_path / "runtime",
    )

    result = asyncio.run(
        runner.run(
            _manifests(base_sha),
            _factory(created_agents),
            repeats=3,
            study_id="study-smoke",
            n_bootstraps=200,
        )
    )

    assert result.repeat_count == 3
    assert result.repeat_seeds == (17, 23, 28)
    assert len(result.repeats) == 3
    assert len(created_agents) == 9
    execution_orders = [tuple(item.execution_order) for item in result.repeats]
    assert execution_orders == [
        ("B3", "B5", "B7"),
        ("B7", "B3", "B5"),
        ("B5", "B7", "B3"),
    ]
    for position in range(3):
        assert {order[position] for order in execution_orders} == {"B3", "B5", "B7"}
    assert all(item.base_commit == base_sha for item in result.repeats)

    assert len(result.aggregates) == 3
    for aggregate in result.aggregates:
        assert aggregate.repetitions == 3
        assert aggregate.resolved_rate_delta.sample_count == 3
        assert aggregate.resolved_rate_delta.mean_delta == 0.0
        assert aggregate.resolved_rate_delta.ci_lower == 0.0
        assert aggregate.resolved_rate_delta.ci_upper == 0.0

    assert result.provenance["base_commit"] == base_sha
    assert result.provenance["repeat_seeds"] == [17, 23, 28]
    assert result.provenance["order_schedule"] == "balanced_crossover_v1"
    assert result.provenance["agent_fingerprint"]["adapter_type"].endswith(
        ".MockAgentAdapter"
    )
    assert set(result.provenance["manifest_digests"]) == {"B3", "B5", "B7"}

    assert (result.artifact_dir / "study.json").exists()
    assert (result.artifact_dir / "provenance.json").exists()
    assert (result.artifact_dir / "aggregates.json").exists()
    assert not (tmp_path / "runtime" / "study-smoke").exists()

    source_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source_head == base_sha
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"


def test_repeated_runner_rejects_agent_reuse_across_repetitions(tmp_path: Path) -> None:
    repo, base_sha = _git_repo(tmp_path)
    reusable = [MockAgentAdapter(name="mock") for _ in range(3)]
    calls = 0

    def cycling_factory() -> MockAgentAdapter:
        nonlocal calls
        agent = reusable[calls % len(reusable)]
        calls += 1
        return agent

    runner = RepeatedPairedBenchmarkRunner(
        repo,
        output_root=tmp_path / "results",
        workspace_root=tmp_path / "runtime",
    )
    with pytest.raises(ValueError, match="fresh adapter instance"):
        asyncio.run(
            runner.run(
                _manifests(base_sha),
                cycling_factory,
                repeats=2,
                study_id="reuse-study",
                n_bootstraps=20,
            )
        )

    failure = (
        runner.output_root
        / "repeated-smoke"
        / "studies"
        / "reuse-study"
        / "failure.json"
    )
    assert failure.exists()
