"""Benchmark runner using trace-derived, nullable research measurements."""

from __future__ import annotations

import math
import subprocess
import time
from statistics import fmean
from typing import Any, List, Optional

from adapters.base import AgentAdapter
from context.policy import ContextPolicy
from eval.baselines.normalized import StaticStructuredContextPolicy, VectorTopKContextPolicy
from eval.grading.hidden_tests import HiddenTestGrader
from eval.models import BenchmarkManifest, EvaluationSummary, TaskMeasurement
from eval.telemetry import collect_trace_telemetry
from runtime.orchestrator import Orchestrator
from state.models import GateStatus

TaskMetric = TaskMeasurement
ExperimentSummary = EvaluationSummary
NORMALIZED_BASELINES = {"B3", "B5", "B7"}



def _mean(values: list[float | int | None]) -> float | None:
    observed = [float(value) for value in values if value is not None]
    return fmean(observed) if observed else None



def _p95(values: list[float | None]) -> float | None:
    observed = sorted(float(value) for value in values if value is not None)
    if not observed:
        return None
    rank = max(1, math.ceil(0.95 * len(observed)))
    return observed[rank - 1]



def summarize_measurements(measurements: list[TaskMeasurement]) -> EvaluationSummary:
    if not measurements:
        raise ValueError("cannot summarize an empty benchmark")

    benchmark_id = measurements[0].benchmark_id
    baseline = measurements[0].baseline
    if any(item.benchmark_id != benchmark_id for item in measurements):
        raise ValueError("all measurements must belong to one benchmark")
    if any(item.baseline != baseline for item in measurements):
        raise ValueError("all measurements must use one baseline")

    costs = [item.cost_usd for item in measurements if item.cost_observed]
    provider_tokens = [
        item.provider_tokens for item in measurements if item.token_usage_observed
    ]
    stale_known = [
        item.stale_memories_delivered
        for item in measurements
        if item.stale_memories_delivered is not None
    ]

    return EvaluationSummary(
        benchmark_id=benchmark_id,
        baseline=baseline,
        total_tasks=len(measurements),
        resolved_count=sum(1 for item in measurements if item.resolved),
        resolved_rate=sum(1 for item in measurements if item.resolved) / len(measurements),
        mean_context_tokens=_mean([item.context_tokens for item in measurements]),
        mean_provider_tokens=_mean(provider_tokens),
        mean_cost_usd=_mean(costs),
        total_cost_usd=sum(float(value) for value in costs) if costs else None,
        cost_coverage=sum(1 for item in measurements if item.cost_observed) / len(measurements),
        token_coverage=(
            sum(1 for item in measurements if item.token_usage_observed) / len(measurements)
        ),
        p95_end_to_end_latency_ms=_p95(
            [item.end_to_end_latency_ms for item in measurements]
        ),
        p95_retrieval_latency_ms=_p95(
            [item.retrieval_latency_ms for item in measurements]
        ),
        stale_delivery_rate=(
            sum(1 for value in stale_known if value > 0) / len(stale_known)
            if stale_known
            else None
        ),
    )


class ExperimentRunner:
    """Run normalized context baselines through one ARC execution/gating path.

    ARC 0.12 normalizes B3, B5, and B7. They differ only in context selection
    and validity semantics; leases, provider budget, worktree isolation,
    candidate creation, staleness checks, IntegrationGate, hidden grading, and
    trace-derived measurement are shared.
    """

    def __init__(
        self,
        grader: Optional[HiddenTestGrader] = None,
        *,
        task_observer: Any | None = None,
    ) -> None:
        self.grader = grader
        self.task_observer = task_observer
        self.last_measurements: list[TaskMeasurement] = []

    @staticmethod
    def _repo_head(orchestrator: Orchestrator) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(orchestrator.repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    @staticmethod
    def _validate_manifest_tasks(
        orchestrator: Orchestrator,
        manifest: BenchmarkManifest,
    ) -> None:
        for spec in manifest.tasks:
            task = orchestrator.scheduler.get_task(spec.task_id)
            if task is None:
                raise ValueError(f"manifest task {spec.task_id} does not exist in ARC state")
            mismatches: list[str] = []
            if task.goal != spec.goal:
                mismatches.append("goal")
            if task.files_declared != spec.files:
                mismatches.append("files")
            if task.acceptance_criteria != spec.acceptance:
                mismatches.append("acceptance")
            if task.risk != spec.risk:
                mismatches.append("risk")
            if task.token_budget != spec.token_budget:
                mismatches.append("token_budget")
            if mismatches:
                raise ValueError(
                    f"manifest task {spec.task_id} does not match ARC task state: "
                    + ", ".join(mismatches)
                )

    @staticmethod
    def _context_policy(
        orchestrator: Orchestrator,
        baseline: str,
    ) -> ContextPolicy | None:
        if baseline == "B7":
            return None
        if baseline == "B3":
            return StaticStructuredContextPolicy(orchestrator.compiler)
        if baseline == "B5":
            return VectorTopKContextPolicy(
                orchestrator.compiler,
                orchestrator.memory_lifecycle,
                top_k=5,
            )
        raise ValueError(
            f"baseline {baseline} is not normalized in ARC 0.12; supported: B3, B5, B7"
        )

    async def run_manifest(
        self,
        orchestrator: Orchestrator,
        manifest: BenchmarkManifest,
        agent: AgentAdapter,
    ) -> ExperimentSummary:
        """Execute a validated normalized manifest from its declared repository base."""
        if manifest.baseline not in NORMALIZED_BASELINES:
            raise ValueError(
                f"ARC 0.12 normalizes B3/B5/B7 only; {manifest.baseline} remains unsupported"
            )
        if manifest.faults:
            raise ValueError(
                "fault-enabled manifests are not executable in ARC 0.12 until a deterministic "
                "fault schedule is wired into the shared runner"
            )
        if (
            manifest.hard_task_usd is not None
            and abs(orchestrator.hard_task_usd - manifest.hard_task_usd) > 1e-12
        ):
            raise ValueError(
                f"runtime hard_task_usd {orchestrator.hard_task_usd} does not match "
                f"manifest hard_task_usd {manifest.hard_task_usd}"
            )

        head = self._repo_head(orchestrator)
        if not head.startswith(manifest.repo_commit) and not manifest.repo_commit.startswith(head):
            raise ValueError(
                f"repository HEAD {head} does not match manifest repo_commit "
                f"{manifest.repo_commit}"
            )
        self._validate_manifest_tasks(orchestrator, manifest)

        patterns = {
            task.task_id: task.hidden_test_pattern
            for task in manifest.tasks
            if task.hidden_test_pattern
        }
        return await self.run_benchmark(
            orchestrator,
            [task.task_id for task in manifest.tasks],
            agent,
            agent_id=manifest.agent_profile,
            benchmark_id=manifest.benchmark_id,
            baseline=manifest.baseline,
            repo_commit=head,
            model=manifest.model,
            seed=manifest.seed,
            fault_kinds=[],
            hidden_test_patterns=patterns,
        )

    async def run_benchmark(
        self,
        orchestrator: Orchestrator,
        task_ids: List[str],
        agent: AgentAdapter,
        agent_id: str = "codex",
        *,
        benchmark_id: str = "arc-benchmark",
        baseline: str = "B7",
        repo_commit: str = "unknown",
        model: str | None = None,
        seed: int = 0,
        fault_kinds: Optional[list[str]] = None,
        hidden_test_patterns: Optional[dict[str, str]] = None,
    ) -> ExperimentSummary:
        if baseline not in NORMALIZED_BASELINES:
            raise ValueError(
                f"ExperimentRunner normalizes B3/B5/B7 only; got {baseline}"
            )
        if not task_ids:
            raise ValueError("task_ids cannot be empty")

        context_policy = self._context_policy(orchestrator, baseline)
        measurements: list[TaskMeasurement] = []
        for task_id in task_ids:
            event_start = orchestrator.event_store.current_version(orchestrator.project_id)
            started = time.perf_counter()
            ticket = self.task_observer.begin_task(task_id) if self.task_observer else None
            try:
                gate_result = await orchestrator.execute_task(
                    task_id,
                    agent,
                    agent_id,
                    context_policy=context_policy,
                    before_provider=(
                        (lambda ticket=ticket: self.task_observer.before_provider(ticket))
                        if self.task_observer and ticket is not None
                        else None
                    ),
                    continue_on_agent_failure=self.task_observer is not None,
                )
            except BaseException:
                if self.task_observer and ticket is not None:
                    self.task_observer.fail_unexpected(ticket)
                raise
            end_to_end_ms = (time.perf_counter() - started) * 1000.0
            event_end = orchestrator.event_store.current_version(orchestrator.project_id)
            events = orchestrator.event_store.read_range(
                event_start + 1,
                event_end,
                project_id=orchestrator.project_id,
            )
            trace = collect_trace_telemetry(events, gate_result)
            if trace.context_policy != baseline:
                raise RuntimeError(
                    f"task {task_id} emitted context policy {trace.context_policy!r}; "
                    f"expected {baseline!r}"
                )

            hidden_passed: bool | None = None
            hidden_count: int | None = None
            if self.grader is not None and gate_result.status == GateStatus.ACCEPTED:
                pattern = (hidden_test_patterns or {}).get(task_id, "test_hidden_*.py")
                grade = self.grader.grade(orchestrator.repo_path, test_file_pattern=pattern)
                hidden_passed = grade.passed
                hidden_count = grade.total_hidden_tests

            measurement = TaskMeasurement(
                    benchmark_id=benchmark_id,
                    baseline=baseline,
                    task_id=task_id,
                    agent_profile=agent_id,
                    model=model,
                    seed=seed,
                    repo_commit=repo_commit,
                    resolved=gate_result.status == GateStatus.ACCEPTED
                    and hidden_passed is not False,
                    gate_status=gate_result.status.value,
                    rejection_stage=gate_result.rejection_stage,
                    context_id=trace.context_id,
                    context_digest=trace.context_digest,
                    context_policy=trace.context_policy,
                    context_tokens=trace.context_tokens,
                    context_hard_budget=trace.context_hard_budget,
                    memory_ids=list(trace.memory_ids),
                    stale_memory_ids=list(trace.stale_memory_ids),
                    retrieval_strategies=list(trace.retrieval_strategies),
                    provider_tokens=trace.provider_tokens,
                    cost_usd=trace.cost_usd,
                    cost_observed=trace.cost_observed,
                    token_usage_observed=trace.token_usage_observed,
                    end_to_end_latency_ms=end_to_end_ms,
                    retrieval_latency_ms=trace.retrieval_latency_ms,
                    context_compile_latency_ms=trace.context_compile_latency_ms,
                    staleness_score=gate_result.staleness_score,
                    stale_memories_delivered=len(trace.stale_memory_ids),
                    retry_count=trace.retry_count,
                    handoff_count=trace.handoff_count,
                    gate_failure_count=trace.gate_failure_count,
                    hidden_tests_passed=hidden_passed,
                    hidden_test_count=hidden_count,
                    fault_kinds=list(fault_kinds or []),
                    event_start=event_start,
                    event_end=event_end,
                    candidate_commit_sha=trace.candidate_commit_sha,
                )
            measurements.append(measurement)
            if self.task_observer and ticket is not None:
                self.task_observer.finish(
                    ticket,
                    result=orchestrator.last_agent_result,
                    completed=gate_result.status == GateStatus.ACCEPTED,
                    measurement=measurement.model_dump(mode="json"),
                )

        self.last_measurements = measurements
        return summarize_measurements(measurements)
