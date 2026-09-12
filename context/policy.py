"""Injectable context-policy interface for normalized execution experiments."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from context.compiler import ContextCompiler, ContextPacket
from context.request import ContextRequest
from context.retrieval import MemoryRetriever
from state.models import ProjectState, TaskState


@dataclass(frozen=True)
class ContextBuildResult:
    """One policy's compiled packet plus directly observed phase timings."""

    packet: ContextPacket
    policy_id: str
    retrieval_latency_ms: float
    compile_latency_ms: float
    retrieval_strategies: tuple[str, ...] = ()


class ContextPolicy(Protocol):
    """Build a ContextPacket while leaving execution/integration unchanged."""

    policy_id: str

    def build(
        self,
        *,
        request: ContextRequest,
        project_state: ProjectState,
        task_state: TaskState,
        active_leases: list[dict[str, Any]],
    ) -> ContextBuildResult:
        ...


class RuntimeContextPolicy:
    """ARC's production provenance-aware context policy (research baseline B7)."""

    policy_id = "B7"

    def __init__(self, retriever: MemoryRetriever, compiler: ContextCompiler) -> None:
        self.retriever = retriever
        self.compiler = compiler

    def build(
        self,
        *,
        request: ContextRequest,
        project_state: ProjectState,
        task_state: TaskState,
        active_leases: list[dict[str, Any]],
    ) -> ContextBuildResult:
        retrieval_started = time.perf_counter()
        retrieval = self.retriever.retrieve(request)
        retrieval_ms = (time.perf_counter() - retrieval_started) * 1000.0

        compile_started = time.perf_counter()
        packet = self.compiler.compile(
            request=request,
            retrieval=retrieval,
            project_state=project_state,
            task_state=task_state,
            active_leases=active_leases,
            policy_id=self.policy_id,
            enforce_memory_validity=True,
        )
        compile_ms = (time.perf_counter() - compile_started) * 1000.0

        return ContextBuildResult(
            packet=packet,
            policy_id=self.policy_id,
            retrieval_latency_ms=retrieval_ms,
            compile_latency_ms=compile_ms,
            retrieval_strategies=tuple(retrieval.strategies_used),
        )
