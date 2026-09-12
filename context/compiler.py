"""Normalized research context policies that share ARC's execution/gate path."""

from __future__ import annotations

import time
from typing import Any

from context.compiler import ContextCompiler
from context.policy import ContextBuildResult
from context.request import ContextRequest
from context.retrieval import RetrievalResult, ScoredCandidate
from indexes.vector import VectorIndex
from memory.lifecycle import MemoryLifecycle
from state.models import ProjectState, TaskState


class StaticStructuredContextPolicy:
    """B3: authoritative task/code context with no long-term memory retrieval."""

    policy_id = "B3"

    def __init__(self, compiler: ContextCompiler) -> None:
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
        retrieval = RetrievalResult(
            candidates=[],
            strategies_used=["static_no_memory"],
            total_found=0,
        )
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


class VectorTopKContextPolicy:
    """B5: naive deterministic vector top-k over persisted non-deleted memory.

    This intentionally ignores supersession and temporal validity when selecting
    memories. It uses the same deterministic lexical-hash embedding substrate as
    ARC's prototype vector index; it must not be described as a semantic-embedding
    baseline unless a pinned semantic embedding provider is introduced separately.
    """

    policy_id = "B5"

    def __init__(
        self,
        compiler: ContextCompiler,
        memory_lifecycle: MemoryLifecycle,
        *,
        top_k: int = 5,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self.compiler = compiler
        self.memory_lifecycle = memory_lifecycle
        self.top_k = top_k

    def _retrieve(self, request: ContextRequest) -> RetrievalResult:
        memories = self.memory_lifecycle.get_project_memories(
            request.project_id,
            include_deleted=False,
        )
        if not memories:
            return RetrievalResult(
                candidates=[],
                strategies_used=["naive_vector_topk"],
                total_found=0,
            )

        dimension = self.memory_lifecycle.vector_index.dimension
        index = VectorIndex(dimension=dimension)
        by_id = {}
        for memory in memories:
            by_id[memory.memory_id] = memory
            index.add_vector(
                memory.memory_id,
                VectorIndex.deterministic_hash_embed(
                    memory.content_text,
                    dimension=dimension,
                ),
            )

        query = VectorIndex.deterministic_hash_embed(
            request.goal,
            dimension=dimension,
        )
        hits = index.search(query, top_k=self.top_k)
        candidates = [
            ScoredCandidate(
                memory=by_id[memory_id],
                score=float(score),
                retrieval_strategy="naive_vector_topk",
            )
            for memory_id, score in hits
        ]
        return RetrievalResult(
            candidates=candidates,
            strategies_used=["naive_vector_topk"],
            total_found=len(candidates),
        )

    def build(
        self,
        *,
        request: ContextRequest,
        project_state: ProjectState,
        task_state: TaskState,
        active_leases: list[dict[str, Any]],
    ) -> ContextBuildResult:
        retrieval_started = time.perf_counter()
        retrieval = self._retrieve(request)
        retrieval_ms = (time.perf_counter() - retrieval_started) * 1000.0

        compile_started = time.perf_counter()
        packet = self.compiler.compile(
            request=request,
            retrieval=retrieval,
            project_state=project_state,
            task_state=task_state,
            active_leases=active_leases,
            policy_id=self.policy_id,
            enforce_memory_validity=False,
        )
        compile_ms = (time.perf_counter() - compile_started) * 1000.0
        return ContextBuildResult(
            packet=packet,
            policy_id=self.policy_id,
            retrieval_latency_ms=retrieval_ms,
            compile_latency_ms=compile_ms,
            retrieval_strategies=tuple(retrieval.strategies_used),
        )
