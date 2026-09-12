"""Comparison tests prevent invalid baseline claims."""

from __future__ import annotations

import pytest

from eval.comparison import compare_paired_measurements, validate_comparable_manifests
from eval.models import BenchmarkManifest, EvaluationTaskSpec, TaskMeasurement


def _manifest(baseline: str, *, budget: int = 8000, commit: str = "abcdef1") -> BenchmarkManifest:
    return BenchmarkManifest(
        benchmark_id=f"bench-{baseline}",
        baseline=baseline,
        seed=7,
        agent_profile="builder",
        model="model-x",
        repo_commit=commit,
        context_token_budget=budget,
        hard_task_usd=1.0,
        tasks=[
            EvaluationTaskSpec(
                task_id="T001",
                goal="fix parser",
                files=["src/parser.py"],
                acceptance=["tests pass"],
                token_budget=budget,
            )
        ],
    )


def _sequence_manifest(baseline: str, task_order: list[str]) -> BenchmarkManifest:
    specs = {
        "T001": EvaluationTaskSpec(
            task_id="T001",
            goal="fix parser",
            files=["src/parser.py"],
            acceptance=["parser tests pass"],
            token_budget=8000,
        ),
        "T002": EvaluationTaskSpec(
            task_id="T002",
            goal="update serializer",
            files=["src/serializer.py"],
            acceptance=["serializer tests pass"],
            token_budget=8000,
        ),
    }
    return BenchmarkManifest(
        benchmark_id=f"sequence-{baseline}",
        baseline=baseline,
        execution_mode="sequence",
        seed=7,
        agent_profile="builder",
        model="model-x",
        repo_commit="abcdef1",
        context_token_budget=8000,
        hard_task_usd=1.0,
        tasks=[specs[task_id] for task_id in task_order],
    )


def _measurement(baseline: str, task_id: str, resolved: bool, tokens: int) -> TaskMeasurement:
    return TaskMeasurement(
        benchmark_id=f"bench-{baseline}",
        baseline=baseline,
        task_id=task_id,
        agent_profile="builder",
        model="model-x",
        seed=7,
        repo_commit="abcdef1",
        resolved=resolved,
        gate_status="accepted" if resolved else "rejected",
        context_tokens=tokens,
        context_hard_budget=8000,
        end_to_end_latency_ms=100.0,
        event_start=1,
        event_end=2,
    )


def test_comparable_manifests_allow_only_baseline_policy_to_differ() -> None:
    validate_comparable_manifests(_manifest("B3"), _manifest("B7"))


def test_comparable_manifests_reject_budget_or_repo_drift() -> None:
    with pytest.raises(ValueError, match="context_token_budget"):
        validate_comparable_manifests(_manifest("B3"), _manifest("B7", budget=9000))

    with pytest.raises(ValueError, match="repo_commit"):
        validate_comparable_manifests(
            _manifest("B3"),
            _manifest("B7", commit="fffffff"),
        )


def test_comparable_sequence_manifests_reject_reordered_tasks() -> None:
    left = _sequence_manifest("B3", ["T001", "T002"])
    right = _sequence_manifest("B7", ["T002", "T001"])

    with pytest.raises(ValueError, match="ordered task IDs"):
        validate_comparable_manifests(left, right)


def test_paired_comparison_uses_task_level_outcomes() -> None:
    left = [
        _measurement("B3", "T001", False, 7000),
        _measurement("B3", "T002", True, 7100),
        _measurement("B3", "T003", True, 6900),
    ]
    right = [
        _measurement("B7", "T001", True, 7000),
        _measurement("B7", "T002", True, 7000),
        _measurement("B7", "T003", False, 7000),
    ]

    comparison = compare_paired_measurements(left, right)

    assert comparison.task_count == 3
    assert comparison.wins_a == 1
    assert comparison.wins_b == 1
    assert comparison.ties == 1
    assert comparison.resolved_delta == pytest.approx(0.0)
    assert comparison.mean_context_tokens_a == pytest.approx(7000.0)
    assert comparison.mean_context_tokens_b == pytest.approx(7000.0)
