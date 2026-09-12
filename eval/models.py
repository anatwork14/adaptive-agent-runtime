"""Serializable research-evaluation models for reproducible ARC experiments.

Evaluation records are deliberately separate from authoritative runtime state.
They reference authoritative events/Git outcomes but never replace them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


BaselineId = Literal["B0", "B2", "B3", "B5", "B7"]
ExecutionMode = Literal["sequence"]


class EvaluationTaskSpec(BaseModel):
    """One benchmark task with a fixed correctness contract."""

    task_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    token_budget: int = Field(default=24000, ge=1)
    hidden_test_pattern: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FaultSpec(BaseModel):
    """Declared fault injection; undeclared faults invalidate a benchmark run."""

    kind: str = Field(min_length=1)
    target: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class BenchmarkManifest(BaseModel):
    """Immutable-by-convention description of one ordered benchmark scenario."""

    benchmark_id: str = Field(min_length=1)
    baseline: BaselineId
    execution_mode: ExecutionMode = "sequence"
    seed: int = 0
    agent_profile: str = Field(min_length=1)
    model: str | None = None
    repo_commit: str = Field(min_length=7, max_length=40, pattern=r"^[0-9a-fA-F]+$")
    context_token_budget: int = Field(ge=1)
    hard_task_usd: float | None = Field(default=None, ge=0.0)
    tasks: list[EvaluationTaskSpec] = Field(min_length=1)
    faults: list[FaultSpec] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def enforce_matched_task_budget(self) -> "BenchmarkManifest":
        """Prevent accidental baseline comparisons with different declared budgets."""
        mismatched = [
            task.task_id
            for task in self.tasks
            if task.token_budget != self.context_token_budget
        ]
        if mismatched:
            joined = ", ".join(mismatched)
            raise ValueError(
                "all tasks must use manifest context_token_budget for matched-budget "
                f"evaluation; mismatched tasks: {joined}"
            )
        return self


class TaskMeasurement(BaseModel):
    """Trace-derived outcome for one task.

    Nullable fields mean ARC did not observe authoritative/explicit telemetry for
    that quantity. Unknown is never coerced to zero for research reporting.
    """

    benchmark_id: str
    baseline: BaselineId
    task_id: str
    agent_profile: str
    model: str | None = None
    seed: int = 0
    repo_commit: str

    resolved: bool
    gate_status: str
    rejection_stage: str | None = None
    context_id: str | None = None
    context_digest: str | None = None
    context_policy: str | None = None
    context_tokens: int | None = None
    context_hard_budget: int | None = None
    memory_ids: list[str] = Field(default_factory=list)
    stale_memory_ids: list[str] = Field(default_factory=list)
    retrieval_strategies: list[str] = Field(default_factory=list)

    provider_tokens: int | None = None
    cost_usd: float | None = None
    cost_observed: bool = False
    token_usage_observed: bool = False

    end_to_end_latency_ms: float
    retrieval_latency_ms: float | None = None
    context_compile_latency_ms: float | None = None

    staleness_score: float | None = None
    stale_memories_delivered: int | None = None
    retry_count: int = 0
    handoff_count: int = 0
    gate_failure_count: int = 0

    hidden_tests_passed: bool | None = None
    hidden_test_count: int | None = None
    fault_kinds: list[str] = Field(default_factory=list)

    event_start: int
    event_end: int
    candidate_commit_sha: str | None = None


class EvaluationSummary(BaseModel):
    benchmark_id: str
    baseline: BaselineId
    total_tasks: int
    resolved_count: int
    resolved_rate: float
    mean_context_tokens: float | None = None
    mean_provider_tokens: float | None = None
    mean_cost_usd: float | None = None
    total_cost_usd: float | None = None
    cost_coverage: float = 0.0
    token_coverage: float = 0.0
    p95_end_to_end_latency_ms: float | None = None
    p95_retrieval_latency_ms: float | None = None
    stale_delivery_rate: float | None = None
