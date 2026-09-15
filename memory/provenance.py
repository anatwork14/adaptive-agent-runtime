"""Provenance tracking and validity boundary verification for memories."""

from memory.models import Memory, MemoryStatus


class ProvenanceVerifier:
    """Enforces Invariants I4 and I5: All memories must carry source events and temporal validity."""

    @staticmethod
    def validate_memory(memory: Memory) -> None:
        """Validate that a memory conforms to system invariants."""
        # I4: Every memory has provenance
        if not memory.source_events or len(memory.source_events) == 0:
            raise ValueError(f"Invariant I4 violated: Memory {memory.memory_id} has no source event IDs")

        # I5: Temporal validity
        if memory.created_event <= 0:
            raise ValueError(f"Invariant I5 violated: Memory {memory.memory_id} created_event must be positive")
        if memory.valid_from_event <= 0:
            raise ValueError(f"Invariant I5 violated: Memory {memory.memory_id} valid_from_event must be positive")
        if memory.valid_to_event is not None and memory.valid_to_event < memory.valid_from_event:
            raise ValueError(
                f"Invariant I5 violated: valid_to_event ({memory.valid_to_event}) cannot precede "
                f"valid_from_event ({memory.valid_from_event})"
            )
        if memory.status == MemoryStatus.SUPERSEDED and not memory.superseded_by:
            # Memory marked superseded should point to what replaced it
            pass

    @staticmethod
    def is_valid_at_version(memory: Memory, state_version: int) -> bool:
        """Check if memory was valid at a specific state version."""
        if memory.status == MemoryStatus.DELETED:
            return False
        if memory.valid_from_event > state_version:
            return False
        if memory.valid_to_event is not None and memory.valid_to_event < state_version:
            return False
        return True
