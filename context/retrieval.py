"""Retrieval router executing ordered retrieval strategies across authoritative and derived stores."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from context.ranking import CandidateRanker
from context.request import ContextRequest
from memory.lifecycle import MemoryLifecycle
from memory.models import Memory, MemoryType


@dataclass
class ScoredCandidate:
    memory: Memory
    score: float
    retrieval_strategy: str


@dataclass
class RetrievalResult:
    candidates: List[ScoredCandidate] = field(default_factory=list)
    strategies_used: List[str] = field(default_factory=list)
    total_found: int = 0


class MemoryRetriever:
    """Orchestrates retrieval strategies: authoritative, active decisions, symbols, lexical FTS, vector."""

    def __init__(
        self,
        memory_lifecycle: MemoryLifecycle,
        ranker: Optional[CandidateRanker] = None,
    ) -> None:
        self.lifecycle = memory_lifecycle
        self.ranker = ranker or CandidateRanker()

    @staticmethod
    def _eligible_for_generic_retrieval(mem: Memory, request: ContextRequest) -> bool:
        """Keep episodic history dependency-scoped when provenance is available.

        TASK_SUMMARY/EPISODE memories are the dominant successful-run memory
        produced by subprocess coding agents. If a task declares dependencies,
        those summaries should enter through the dependency-linked route rather
        than being re-expanded indiscriminately by lexical/vector fallback.

        This preserves generic semantic retrieval for root tasks while making the
        runtime policy genuinely provenance-aware on progressive task sequences.
        Non-episodic memory classes keep their existing fallback behavior.
        """
        if mem.type not in (MemoryType.TASK_SUMMARY, MemoryType.EPISODE):
            return True
        if not request.dependencies:
            return True
        return any(dep in mem.tags for dep in request.dependencies)

    def retrieve(self, request: ContextRequest) -> RetrievalResult:
        """Execute ordered retrieval router and return scored, filtered candidates."""
        strategies_used: List[str] = []
        candidates_by_id: Dict[str, ScoredCandidate] = {}

        # 1. Authoritative lookup & Active decisions / constraints
        active_memories = self.lifecycle.get_active_memories(
            project_id=request.project_id,
            state_version=request.state_version,
        )
        strategies_used.append("authoritative_lookup")

        for mem in active_memories:
            if mem.type in (MemoryType.CONSTRAINT, MemoryType.DECISION, MemoryType.FACT):
                score = self.ranker.score_candidate(mem, request, semantic_relevance=1.0)
                if score > 0:
                    candidates_by_id[mem.memory_id] = ScoredCandidate(
                        memory=mem,
                        score=score,
                        retrieval_strategy="active_decisions_and_constraints",
                    )
        strategies_used.append("active_decisions_and_constraints")

        # 2. Dependency-linked memory
        for mem in active_memories:
            if any(dep in mem.tags for dep in request.dependencies):
                score = self.ranker.score_candidate(mem, request, semantic_relevance=0.8)
                if score > 0 and mem.memory_id not in candidates_by_id:
                    candidates_by_id[mem.memory_id] = ScoredCandidate(
                        memory=mem,
                        score=score,
                        retrieval_strategy="dependency_linked_memory",
                    )
        strategies_used.append("dependency_linked_memory")

        # 3. Failures & procedures
        for mem in active_memories:
            if mem.type in (MemoryType.FAILURE, MemoryType.PROCEDURE):
                score = self.ranker.score_candidate(mem, request, semantic_relevance=0.7)
                if score > 0 and mem.memory_id not in candidates_by_id:
                    candidates_by_id[mem.memory_id] = ScoredCandidate(
                        memory=mem,
                        score=score,
                        retrieval_strategy="failures_and_procedures",
                    )
        strategies_used.append("failures_and_procedures")

        # 4. Lexical FTS retrieval
        search_query = f"{request.goal} {' '.join(request.symbols)} {' '.join(request.files_declared)}"
        fts_hits = self.lifecycle.lexical_index.search(search_query, limit=10)
        for mem_id, _rank in fts_hits:
            if mem_id not in candidates_by_id:
                mem = self.lifecycle.get_memory(mem_id)
                if mem and self._eligible_for_generic_retrieval(mem, request):
                    score = self.ranker.score_candidate(mem, request, semantic_relevance=0.6)
                    if score > 0:
                        candidates_by_id[mem.memory_id] = ScoredCandidate(
                            memory=mem,
                            score=score,
                            retrieval_strategy="lexical_retrieval",
                        )
        strategies_used.append("lexical_retrieval")

        # 5. Vector retrieval expansion (fallback / expansion)
        query_vec = self.lifecycle.vector_index.mock_embed_text(request.goal)
        vector_hits = self.lifecycle.vector_index.search(query_vec, top_k=5)
        for mem_id, sim in vector_hits:
            if mem_id not in candidates_by_id:
                mem = self.lifecycle.get_memory(mem_id)
                if mem and self._eligible_for_generic_retrieval(mem, request):
                    score = self.ranker.score_candidate(mem, request, semantic_relevance=float(sim))
                    if score > 0:
                        candidates_by_id[mem.memory_id] = ScoredCandidate(
                            memory=mem,
                            score=score,
                            retrieval_strategy="vector_retrieval",
                        )
        strategies_used.append("vector_retrieval")

        # Sort all candidates by score descending
        sorted_candidates = sorted(candidates_by_id.values(), key=lambda c: c.score, reverse=True)

        return RetrievalResult(
            candidates=sorted_candidates,
            strategies_used=strategies_used,
            total_found=len(sorted_candidates),
        )
