"""Research-evaluation regressions: unknown telemetry must never be fabricated."""

from __future__ import annotations

import pytest

from eval.models import BenchmarkManifest, EvaluationTaskSpec, TaskMeasurement
from eval.runners.experiment import summarize_measurements
from eval.telemetry import collect_trace_telemetry
from state.models import Event, GateResult, GateStatus


def _event(event_id: int, kind: str, payload: dict, task_id: str = "T001") -> Event:
    return Event(
        id=event_id,
        actor="test",
        kind=kind,
        project_id="eval",
        task_id=task_id,
        payload=payload,
        content_hash=f"hash-{event_id}",
    )


def _gate(status: GateStatus = GateStatus.ACCEPTED) -> GateResult:
    return GateResult(
        gate_run_id="gate_eval",
        patch_id="patch_eval",
        task_id="T001",
        agent_id="mock",
        dispatch_state_version=1,
        gate_state_version=2,
        status=status,
        staleness_score=0.25,
        verification_level="V0",
        merged_commit_sha="abc1234" if status == GateStatus.ACCEPTED else None,
    )


def test_trace_collector_preserves_unknown_zero_provider_telemetry() -> None:
    events = [
        _event(
            2,
            "context.compiled",
            {
                "context_id": "CTX_1",
                "digest": "sha256:ctx",
                "token_count": 1234,
                "hard_budget": 24000,
                "memory_ids": ["M1", "M2"],
            },
        ),
        _event(3, "budget.consumed", {"usd": 0.0, "tokens": 0}),
        _event(4, "task.submitted", {"candidate_commit_sha": "deadbeef"}),
    ]

    trace = collect_trace_telemetry(events, _gate())

    assert trace.context_tokens == 1234
    assert trace.context_hard_budget == 24000
    assert trace.memory_ids == ("M1", "M2")
    assert trace.provider_tokens is None
    assert trace.cost_usd is None
    assert not trace.token_usage_observed
    assert not trace.cost_observed
    assert trace.candidate_commit_sha == "deadbeef"


def test_trace_collector_aggregates_only_observed_usage() -> None:
    events = [
        _event(2, "budget.consumed", {"usd": 0.12, "tokens": 900}),
        _event(3, "budget.consumed", {"usd": 0.08, "tokens": 100}),
        _event(4, "task.dispatched", {}),
        _event(5, "task.dispatched", {}),
        _event(6, "gate.rejected", {}),
        _event(7, "recovery.retry", {}),
    ]

    trace = collect_trace_telemetry(events, _gate(GateStatus.REJECTED))

    assert trace.provider_tokens == 1000
    assert trace.cost_usd == pytest.approx(0.20)
    assert trace.token_usage_observed
    assert trace.cost_observed
    assert trace.handoff_count == 1
    assert trace.gate_failure_count == 1
    assert trace.retry_count == 1


def test_trace_collector_ignores_concurrent_other_task_events() -> None:
    events = [
        _event(2, "budget.consumed", {"usd": 0.10, "tokens": 100}),
        _event(3, "budget.consumed", {"usd": 9.99, "tokens": 99999}, task_id="T_OTHER"),
        _event(
            4,
            "context.compiled",
            {"context_id": "CTX_OTHER", "token_count": 7777, "hard_budget": 8000},
            task_id="T_OTHER",
        ),
        _event(
            5,
            "context.compiled",
            {"context_id": "CTX_TARGET", "token_count": 1200, "hard_budget": 8000},
        ),
    ]

    trace = collect_trace_telemetry(events, _gate())

    assert trace.cost_usd == pytest.approx(0.10)
    assert trace.provider_tokens == 100
    assert trace.context_id == "CTX_TARGET"
    assert trace.context_tokens == 1200


def test_manifest_rejects_unmatched_context_budgets() -> None:
    with pytest.raises(ValueError, match="matched-budget"):
        BenchmarkManifest(
            benchmark_id="iso-budget",
            baseline="B7",
            agent_profile="mock",
            repo_commit="abcdef1",
            context_token_budget=8000,
            tasks=[
                EvaluationTaskSpec(
                    task_id="T001",
                    goal="change code",
                    token_budget=4000,
                )
            ],
        )


def test_summary_reports_coverage_and_never_coerces_unknown_to_zero() -> None:
    common = dict(
        benchmark_id="bench",
        baseline="B7",
        agent_profile="mock",
        seed=0,
        repo_commit="abcdef1",
        gate_status="accepted",
        event_start=1,
        event_end=2,
    )
    measurements = [
        TaskMeasurement(
            **common,
            task_id="T001",
            resolved=True,
            context_tokens=1000,
            provider_tokens=500,
            token_usage_observed=True,
            cost_usd=0.1,
            cost_observed=True,
            end_to_end_latency_ms=10.0,
        ),
        TaskMeasurement(
            **common,
            task_id="T002",
            resolved=False,
            context_tokens=1200,
            provider_tokens=None,
            token_usage_observed=False,
            cost_usd=None,
            cost_observed=False,
            end_to_end_latency_ms=20.0,
        ),
    ]

    summary = summarize_measurements(measurements)

    assert summary.resolved_rate == pytest.approx(0.5)
    assert summary.mean_context_tokens == pytest.approx(1100.0)
    assert summary.mean_provider_tokens == pytest.approx(500.0)
    assert summary.mean_cost_usd == pytest.approx(0.1)
    assert summary.cost_coverage == pytest.approx(0.5)
    assert summary.token_coverage == pytest.approx(0.5)
    assert summary.p95_end_to_end_latency_ms == pytest.approx(20.0)
    assert summary.p95_retrieval_latency_ms is None
    assert summary.stale_delivery_rate is None
