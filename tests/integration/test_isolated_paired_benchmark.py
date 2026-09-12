from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from adapters.base import AgentRunResult
from adapters.mock import MockAgentAdapter
from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.runners.paired import IsolatedPairedBenchmarkRunner


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
            benchmark_id="paired-smoke",
            baseline=baseline,
            seed=17,
            agent_profile="mock",
            model="mock-v1",
            repo_commit=repo_sha,
            context_token_budget=4000,
            hard_task_usd=1.0,
            project_constraints=["offline"],
            tasks=[task.model_copy(deep=True) for task in tasks],
        )
        for baseline in ("B3", "B5", "B7")
    ]


def test_isolated_triplet_resets_git_state_memory_and_provider_metadata(tmp_path: Path) -> None:
    repo, base_sha = _git_repo(tmp_path)
    source_head_before = base_sha
    contexts_by_agent: list[list] = []

    def factory() -> MockAgentAdapter:
        seen = []
        contexts_by_agent.append(seen)

        def handler(context, workspace: Path) -> AgentRunResult:
            seen.append(context)
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

    output_root = tmp_path / "results"
    workspace_root = tmp_path / "runtime"
    runner = IsolatedPairedBenchmarkRunner(
        repo,
        output_root=output_root,
        workspace_root=workspace_root,
    )
    result = asyncio.run(
        runner.run(_manifests(base_sha), factory, run_id="smoke-001")
    )

    assert set(result.runs) == {"B3", "B5", "B7"}
    assert len(result.comparisons) == 3
    assert set(result.execution_order) == {"B3", "B5", "B7"}
    assert all(run.initial_commit == base_sha for run in result.runs.values())
    assert all(run.summary.resolved_rate == 1.0 for run in result.runs.values())
    assert all(run.event_count > 0 for run in result.runs.values())

    source_head_after = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source_head_after == source_head_before
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"

    # Workspaces and their ARC runtime scaffolding are disposable; only audit
    # artifacts survive under output_root.
    run_workspace_root = workspace_root / "smoke-001"
    assert not list(run_workspace_root.glob("w[0-9][0-9]-*"))
    assert not (run_workspace_root / ".arc-runtime").exists()
    for baseline in ("b3", "b5", "b7"):
        baseline_dir = result.artifact_dir / baseline
        assert (baseline_dir / "state.db").exists()
        assert (baseline_dir / "memory.db").exists()
        assert (baseline_dir / "manifest.json").exists()
        assert (baseline_dir / "measurements.jsonl").exists()
        assert (baseline_dir / "summary.json").exists()
        assert (baseline_dir / "events.jsonl").exists()
        assert (baseline_dir / "final_head.txt").exists()
    assert (result.artifact_dir / "paired_run.json").exists()

    # Factory order follows the seed-shuffled execution order. The provider sees
    # no treatment labels, but semantic memory content remains treatment-dependent.
    contexts = {
        baseline: contexts_by_agent[index]
        for index, baseline in enumerate(result.execution_order)
    }
    for baseline_contexts in contexts.values():
        assert len(baseline_contexts) == 2
        assert all(context.context_policy == "BLINDED" for context in baseline_contexts)
        assert all(context.memory_ids == [] for context in baseline_contexts)
        assert all(context.retrieval_strategies == [] for context in baseline_contexts)

    assert contexts["B3"][1].decisions == []
    assert contexts["B5"][1].decisions
    assert contexts["B7"][1].decisions

    # Fresh event stores mean corresponding first-task measurements start from
    # the same authoritative version before treatment-specific evolution.
    first_starts = {
        baseline: result.runs[baseline].measurements[0].event_start
        for baseline in ("B3", "B5", "B7")
    }
    assert len(set(first_starts.values())) == 1
