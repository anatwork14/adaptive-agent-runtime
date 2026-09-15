"""Candidate scoring and hard filtering for memory retrieval."""

from typing import Dict, Optional

from context.request import ContextRequest
from memory.models import Memory, MemoryStatus, MemoryType


class CandidateRanker:
    """Scores candidate memories for a context request according to multicriteria weights."""

    DEFAULT_WEIGHTS = {
        "wr": 1.0,  # semantic relevance
        "wa": 1.5,  # authority
        "wf": 1.2,  # freshness
        "ws": 1.0,  # scope match
        "wd": 1.3,  # dependency match
        "wu": 0.8,  # historical utility
        "wc": 0.9,  # confidence
        "wx": 2.0,  # contradiction risk
        "wt": 0.001,  # token cost
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}

    def passes_hard_filters(self, memory: Memory, request: ContextRequest) -> bool:
        """Enforce hard filters before candidate scoring."""
        # 1. Project ID match
        if memory.project_id != request.project_id:
            return False

        # 2. Source events must exist (Invariant I4)
        if not memory.source_events:
            return False

        # 3. Status must be active (or disputed) - never superseded or deleted
        if memory.status in (MemoryStatus.SUPERSEDED, MemoryStatus.DELETED, MemoryStatus.ARCHIVED):
            return False

        # 4. Temporal validity relative to requested state_version
        if memory.valid_from_event > request.state_version:
            return False
        if memory.valid_to_event is not None and memory.valid_to_event < request.state_version:
            return False

        return True

    def score_candidate(
        self,
        memory: Memory,
        request: ContextRequest,
        semantic_relevance: float = 0.5,
    ) -> float:
        """Compute score(m, q) based on specification formula."""
        if not self.passes_hard_filters(memory, request):
            return -999.0

        # Authority
        authority = 1.0 if memory.producer_type == "deterministic" else 0.5
        if memory.type in (MemoryType.CONSTRAINT, MemoryType.DECISION):
            authority += 0.5

        # Freshness: scale difference between request.state_version and memory.created_event
        event_gap = max(0, request.state_version - memory.created_event)
        freshness = max(0.0, 1.0 - (event_gap / 2000.0))

        # Scope match: check if memory tags overlap with declared files / symbols
        scope_hits = 0
        search_terms = set(request.files_declared + request.symbols + [request.task_id])
        for tag in memory.tags:
            if tag in search_terms:
                scope_hits += 1
        scope_match = min(2.0, scope_hits * 0.5)

        # Dependency match: check if memory is linked to dependency tasks
        dep_hits = sum(1 for dep in request.dependencies if dep in memory.tags)
        dependency_match = min(2.0, dep_hits * 1.0)

        # Historical utility
        historical_utility = min(2.0, memory.access_count * 0.1)

        # Confidence
        confidence = memory.confidence

        # Contradiction risk
        contradiction_risk = 1.0 if memory.status == MemoryStatus.DISPUTED else 0.0

        # Token cost
        token_cost = memory.token_size * self.weights["wt"]

        score = (
            self.weights["wr"] * semantic_relevance
            + self.weights["wa"] * authority
            + self.weights["wf"] * freshness
            + self.weights["ws"] * scope_match
            + self.weights["wd"] * dependency_match
            + self.weights["wu"] * historical_utility
            + self.weights["wc"] * confidence
            - self.weights["wx"] * contradiction_risk
            - token_cost
        )
        return round(score, 4)
