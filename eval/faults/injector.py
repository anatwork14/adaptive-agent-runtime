"""Memory and Runtime Fault Injector for evaluating system resilience."""

from enum import Enum

from memory.lifecycle import MemoryLifecycle
from memory.models import Memory, MemoryRepresentation, MemoryStatus, MemoryType
from state.events import EventStore
from state.models import PatchSubmission


class FaultType(str, Enum):
    STALE_STATE_READ = "STALE_STATE_READ"
    SUPERSEDED_MEMORY = "SUPERSEDED_MEMORY"
    MISSING_DECISION = "MISSING_DECISION"
    WRONG_SUMMARY = "WRONG_SUMMARY"
    VECTOR_DISTRACTOR = "VECTOR_DISTRACTOR"
    CONTRADICTORY_ASSUMPTION = "CONTRADICTORY_ASSUMPTION"
    CONTEXT_TRUNCATION = "CONTEXT_TRUNCATION"
    HANDOFF_WITHOUT_FAILURE_HISTORY = "HANDOFF_WITHOUT_FAILURE_HISTORY"
    INDEX_CORRUPTION = "INDEX_CORRUPTION"
    AGENT_KILL = "AGENT_KILL"
    LEASE_EXPIRY = "LEASE_EXPIRY"
    PATCH_CORRUPTION = "PATCH_CORRUPTION"
    BUDGET_EXHAUSTION = "BUDGET_EXHAUSTION"


class FaultInjector:
    """Injects synthetic faults into events, memories, or contexts to test detection and recovery."""

    def __init__(self, event_store: EventStore, memory_lifecycle: MemoryLifecycle) -> None:
        self.event_store = event_store
        self.memory_lifecycle = memory_lifecycle

    def inject_superseded_memory_usage(
        self,
        submission: PatchSubmission,
        superseded_memory_id: str,
    ) -> PatchSubmission:
        """Inject a superseded memory into agent's used memories."""
        sub_dict = submission.model_dump()
        sub_dict["memories_used"].append(superseded_memory_id)
        return PatchSubmission(**sub_dict)

    def inject_contradictory_assumption(
        self,
        project_id: str,
        topic: str,
        created_event: int,
    ) -> Memory:
        """Inject an assumption contradicting an existing topic belief."""
        mem_id = f"M_FAULT_ASSUME_{created_event}"
        mem = Memory(
            memory_id=mem_id,
            project_id=project_id,
            type=MemoryType.ASSUMPTION,
            representation=MemoryRepresentation.STRUCTURED_FACT,
            content_json={"topic": topic, "polarity": True},
            content_text=f"Injected assumption contradicting {topic}",
            created_event=created_event,
            valid_from_event=created_event,
            state_version_at_write=created_event,
            status=MemoryStatus.ACTIVE,
            source_events=[created_event],
        )
        self.memory_lifecycle.save_memory(mem)
        return mem

    def inject_vector_distractor(
        self,
        project_id: str,
        query_text: str,
        created_event: int,
    ) -> Memory:
        """Inject an irrelevant memory having high lexical/vector similarity with query_text."""
        mem_id = f"M_DISTRACT_{created_event}"
        distractor = Memory(
            memory_id=mem_id,
            project_id=project_id,
            type=MemoryType.FACT,
            representation=MemoryRepresentation.STRUCTURED_FACT,
            content_json={"subject": "distractor", "predicate": "unrelated", "object": 999},
            content_text=f"Distractor with keyword: {query_text}",
            created_event=created_event,
            valid_from_event=created_event,
            state_version_at_write=created_event,
            status=MemoryStatus.ACTIVE,
            source_events=[created_event],
        )
        self.memory_lifecycle.save_memory(distractor)
        return distractor

    def inject_index_corruption(self) -> None:
        """Simulate derived index corruption (e.g. FTS / Vector index deletion)."""
        self.memory_lifecycle.lexical_index.clear()
        self.memory_lifecycle.vector_index.clear()
