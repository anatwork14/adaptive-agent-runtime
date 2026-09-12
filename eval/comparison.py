"""Matched-task comparison helpers for ARC benchmark studies."""

from __future__ import annotations

from dataclasses import dataclass

from eval.models import BenchmarkManifest, TaskMeasurement


@dataclass(frozen=True)
class PairedComparison:
    baseline_a: str
    baseline_b: str
    task_count: int
    resolved_rate_a: float
    resolved_rate_b: float
    resolved_delta: float
    wins_a: int
    wins_b: int
    ties: int
    mean_context_tokens_a: float | None
    mean_context_tokens_b: float | None


def validate_comparable_manifests(a: BenchmarkManifest, b: BenchmarkManifest) -> None:
    """Fail closed when a baseline comparison changes more than the policy under test."""
    errors: list[str] = []
    if a.benchmark_id != b.benchmark_id:
        errors.append("benchmark_id differs")
    if a.execution_mode != b.execution_mode:
        errors.append("execution_mode differs")
    if a.repo_commit != b.repo_commit:
        errors.append("repo_commit differs")
    if a.context_token_budget != b.context_token_budget:
        errors.append("context_token_budget differs")
    if a.hard_task_usd != b.hard_task_usd:
        errors.append("hard_task_usd differs")
    if a.agent_profile != b.agent_profile:
        errors.append("agent_profile differs")
    if a.model != b.model:
        errors.append("model differs")
    if a.seed != b.seed:
        errors.append("seed differs")
    if a.project_constraints != b.project_constraints:
        errors.append("project_constraints differ")
    if [fault.model_dump(mode="json") for fault in a.faults] != [
        fault.model_dump(mode="json") for fault in b.faults
    ]:
        errors.append("fault declarations differ")

    # Sequence order is part of the treatment because earlier accepted work and
    # memory become context for later tasks.
    ordered_ids_a = [task.task_id for task in a.tasks]
    ordered_ids_b = [task.task_id for task in b.tasks]
    if ordered_ids_a != ordered_ids_b:
        errors.append("ordered task IDs differ")
    else:
        for left, right in zip(a.tasks, b.tasks):
            fields = (
                "goal",
                "task_type",
                "required_capabilities",
                "dependencies",
                "files",
                "symbols",
                "acceptance",
                "risk",
                "token_budget",
                "hidden_test_pattern",
            )
            for field in fields:
                if getattr(left, field) != getattr(right, field):
                    errors.append(f"task {left.task_id} field {field} differs")

    if errors:
        raise ValueError("incomparable benchmark manifests: " + "; ".join(errors))


def _mean_context(items: list[TaskMeasurement]) -> float | None:
    values = [item.context_tokens for item in items if item.context_tokens is not None]
    return sum(values) / len(values) if values else None


def compare_paired_measurements(
    measurements_a: list[TaskMeasurement],
    measurements_b: list[TaskMeasurement],
) -> PairedComparison:
    """Compare two already-validated result sets on the same task IDs."""
    if not measurements_a or not measurements_b:
        raise ValueError("paired comparison requires non-empty result sets")
    by_a = {item.task_id: item for item in measurements_a}
    by_b = {item.task_id: item for item in measurements_b}
    if len(by_a) != len(measurements_a) or len(by_b) != len(measurements_b):
        raise ValueError("duplicate task IDs are not allowed in paired results")
    if set(by_a) != set(by_b):
        raise ValueError("paired result task IDs differ")

    baseline_a = measurements_a[0].baseline
    baseline_b = measurements_b[0].baseline
    if any(item.baseline != baseline_a for item in measurements_a):
        raise ValueError("result set A mixes baselines")
    if any(item.baseline != baseline_b for item in measurements_b):
        raise ValueError("result set B mixes baselines")

    wins_a = wins_b = ties = 0
    for task_id in sorted(by_a):
        a_resolved = by_a[task_id].resolved
        b_resolved = by_b[task_id].resolved
        if a_resolved and not b_resolved:
            wins_a += 1
        elif b_resolved and not a_resolved:
            wins_b += 1
        else:
            ties += 1

    count = len(by_a)
    rate_a = sum(1 for item in measurements_a if item.resolved) / count
    rate_b = sum(1 for item in measurements_b if item.resolved) / count
    return PairedComparison(
        baseline_a=baseline_a,
        baseline_b=baseline_b,
        task_count=count,
        resolved_rate_a=rate_a,
        resolved_rate_b=rate_b,
        resolved_delta=rate_a - rate_b,
        wins_a=wins_a,
        wins_b=wins_b,
        ties=ties,
        mean_context_tokens_a=_mean_context(measurements_a),
        mean_context_tokens_b=_mean_context(measurements_b),
    )
