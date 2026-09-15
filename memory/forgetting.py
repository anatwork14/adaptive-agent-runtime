"""Controlled forgetting and archival of low-value derived memory objects."""

from typing import List, Set

from memory.models import Memory, MemoryStatus, MemoryType


class MemoryForgettingEngine:
    """Manages archival and retention of derived memory objects without modifying authoritative events."""

    HARD_RETAIN_TYPES = {
        MemoryType.CONSTRAINT,
        MemoryType.DECISION,
    }

    @classmethod
    def compute_keep_score(
        cls,
        memory: Memory,
        current_event_id: int,
        active_task_tags: Set[str],
    ) -> float:
        # Invariant: Hard-retain classes are never forgotten
        if memory.type in cls.HARD_RETAIN_TYPES and memory.status == MemoryStatus.ACTIVE:
            return 999.0

        staleness = max(0.0, (current_event_id - memory.created_event) / 1000.0)
        access_utility = min(2.0, memory.access_count * 0.2)
        
        # Dependency reach: check if memory tags match any active task
        dependency_reach = 1.0 if any(t in active_task_tags for t in memory.tags) else 0.0

        keep_score = (
            memory.importance
            + memory.predicted_reuse
            + access_utility
            + dependency_reach
            + memory.confidence
            - staleness
        )
        return keep_score

    @classmethod
    def archive_low_value(
        cls,
        memories: List[Memory],
        current_event_id: int,
        active_task_tags: Set[str],
        archive_threshold: float = 0.5,
    ) -> List[Memory]:
        """Mark memories with keep_score below threshold as ARCHIVED."""
        archived: List[Memory] = []
        for mem in memories:
            if mem.status != MemoryStatus.ACTIVE:
                continue
            score = cls.compute_keep_score(mem, current_event_id, active_task_tags)
            if score < archive_threshold:
                mem.status = MemoryStatus.ARCHIVED
                archived.append(mem)
        return archived
