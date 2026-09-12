"""Trace-derived measurements for ARC research evaluation.

This module never fabricates provider telemetry. Values ARC did not observe are
returned as ``None`` so downstream summaries can report measurement coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from state.models import Event, GateResult


@dataclass(frozen=True)
class TraceTelemetry:
    context_id: str | None = None
    context_digest: str | None = None
    context_tokens: int | None = None
    context_hard_budget: int | None = None
    memory_ids: tuple[str, ...] = ()
    provider_tokens: int | None = None
    cost_usd: float | None = None
    token_usage_observed: bool = False
    cost_observed: bool = False
    retry_count: int = 0
    handoff_count: int = 0
    gate_failure_count: int = 0
    candidate_commit_sha: str | None = None


def collect_trace_telemetry(events: Iterable[Event], gate_result: GateResult) -> TraceTelemetry:
    """Extract only quantities evidenced by the event slice for one task.

    Existing ``budget.consumed`` events predate explicit telemetry-availability
    flags. Conservatively, zero values are treated as unobserved rather than
    claiming a provider was free or used zero tokens.
    """
    context_id: str | None = None
    context_digest: str | None = None
    context_tokens: int | None = None
    context_hard_budget: int | None = None
    memory_ids: tuple[str, ...] = ()
    provider_tokens_total = 0
    cost_total = 0.0
    token_observed = False
    cost_observed = False
    retry_count = 0
    dispatch_count = 0
    gate_failure_count = 0
    candidate_commit_sha: str | None = None

    for event in events:
        payload = event.payload
        if event.kind == "context.compiled":
            context_id = str(payload.get("context_id") or "") or None
            context_digest = str(payload.get("digest") or "") or None
            raw_tokens = payload.get("token_count")
            raw_budget = payload.get("hard_budget")
            context_tokens = int(raw_tokens) if raw_tokens is not None else None
            context_hard_budget = int(raw_budget) if raw_budget is not None else None
            memory_ids = tuple(str(item) for item in payload.get("memory_ids", []))
        elif event.kind == "budget.consumed":
            tokens = int(payload.get("tokens", 0) or 0)
            usd = float(payload.get("usd", 0.0) or 0.0)
            provider_tokens_total += tokens
            cost_total += usd
            token_observed = token_observed or tokens > 0
            cost_observed = cost_observed or usd > 0.0
        elif event.kind in {"recovery.retry", "task.retry_requested"}:
            retry_count += 1
        elif event.kind == "task.dispatched":
            dispatch_count += 1
        elif event.kind == "gate.rejected":
            gate_failure_count += 1
        elif event.kind == "task.submitted":
            raw_sha = payload.get("candidate_commit_sha")
            candidate_commit_sha = str(raw_sha) if raw_sha else candidate_commit_sha

    if candidate_commit_sha is None:
        candidate_commit_sha = getattr(gate_result, "merged_commit_sha", None)

    return TraceTelemetry(
        context_id=context_id,
        context_digest=context_digest,
        context_tokens=context_tokens,
        context_hard_budget=context_hard_budget,
        memory_ids=memory_ids,
        provider_tokens=provider_tokens_total if token_observed else None,
        cost_usd=cost_total if cost_observed else None,
        token_usage_observed=token_observed,
        cost_observed=cost_observed,
        retry_count=retry_count,
        handoff_count=max(0, dispatch_count - 1),
        gate_failure_count=gate_failure_count,
        candidate_commit_sha=candidate_commit_sha,
    )
