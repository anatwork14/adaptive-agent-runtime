"""Memory consolidation combining redundant memories into structured procedures."""

from typing import List, Optional
from state.hashing import compute_hash
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)


class MemoryConsolidator:
    """Consolidates recurring or redundant memories while preserving origin event provenance."""

    @staticmethod
    def consolidate_failures(
        failures: List[Memory],
        project_id: str,
        current_event_id: int,
    ) -> Optional[Memory]:
        """Consolidate 3 or more recurring failures into a reusable procedure."""
        if len(failures) < 3:
            return None

        # Collect all source events
        all_sources: List[int] = []
        error_texts: List[str] = []
        for f in failures:
            all_sources.extend(f.source_events)
            error_texts.append(f.content_text)

        all_sources = sorted(list(set(all_sources)))
        rule_text = f"Known recurring failure across attempts: {failures[0].content_json.get('error')}. Verify prerequisites before running."
        consolidated_id = f"M_CONSOL_PROC_{current_event_id}"

        return Memory(
            memory_id=consolidated_id,
            project_id=project_id,
            type=MemoryType.PROCEDURE,
            representation=MemoryRepresentation.PROCEDURE,
            content_json={
                "rule": rule_text,
                "consolidated_from": [f.memory_id for f in failures],
                "failure_count": len(failures),
            },
            content_text=rule_text,
            created_event=current_event_id,
            valid_from_event=current_event_id,
            state_version_at_write=current_event_id,
            status=MemoryStatus.ACTIVE,
            confidence=0.95,
            importance=0.85,
            predicted_reuse=0.90,
            token_size=len(rule_text.split()) + 15,
            content_hash=compute_hash(rule_text),
            producer_type="consolidator",
            source_events=all_sources,
            tags=["procedure", "consolidated", "failures"],
        )
