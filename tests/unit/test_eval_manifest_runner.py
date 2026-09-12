"""Fail-closed tests for reproducible manifest execution preflight."""

from __future__ import annotations

import pytest

from eval.models import BenchmarkManifest, EvaluationTaskSpec, FaultSpec
from eval.runners.experiment import ExperimentRunner


class _FakeOrchestrator:
    hard_task_usd = 5.0


class _NeverRunAgent:
    async def run(self, **kwargs):  # pragma: no cover - preflight must stop first
        raise AssertionError("agent must not run when manifest preflight fails")


def _manifest(**overrides) -> BenchmarkManifest:
    payload = dict(
        benchmark_id="preflight",
        baseline="B7",
        seed=1,
        agent_profile="mock",
        repo_commit="abcdef1",
        context_token_budget=4000,
        hard_task_usd=5.0,
        tasks=[EvaluationTaskSpec(task_id="T001", goal="fix", token_budget=4000)],
    )
    payload.update(overrides)
    return BenchmarkManifest(**payload)


@pytest.mark.asyncio
async def test_manifest_rejects_runtime_usd_ceiling_mismatch() -> None:
    runner = ExperimentRunner()
    with pytest.raises(ValueError, match="hard_task_usd"):
        await runner.run_manifest(
            _FakeOrchestrator(),  # type: ignore[arg-type]
            _manifest(hard_task_usd=1.0),
            _NeverRunAgent(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_manifest_rejects_faults_until_schedule_is_explicit() -> None:
    runner = ExperimentRunner()
    with pytest.raises(ValueError, match="fault-enabled"):
        await runner.run_manifest(
            _FakeOrchestrator(),  # type: ignore[arg-type]
            _manifest(faults=[FaultSpec(kind="VECTOR_DISTRACTOR")]),
            _NeverRunAgent(),  # type: ignore[arg-type]
        )


def test_manifest_rejects_non_git_repository_identifier() -> None:
    with pytest.raises(ValueError):
        _manifest(repo_commit="not-a-sha")
