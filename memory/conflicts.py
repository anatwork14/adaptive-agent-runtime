"""Conflict detection and supersession management across memories."""

from enum import Enum
from typing import Dict, List, Optional, Tuple
from memory.models import Memory, MemoryStatus, MemoryType


class ConflictClass(str, Enum):
    T0_EXACT_KEY_UPDATE = "T0_exact_key_update"
    T1_TEMPORAL_SUPERSESSION = "T1_temporal_supersession"
    T2_CONTRADICTORY_ASSUMPTIONS = "T2_contradictory_assumptions"
    T3_SEMANTIC_CONFLICT = "T3_semantic_conflict"


class ConflictDetector:
    """Detects conflicts and manages supersession relationships between memory objects."""

    @staticmethod
    def detect_conflicts(
        new_memory: Memory,
        existing_memories: List[Memory],
    ) -> List[Tuple[Memory, ConflictClass, str]]:
        """Identify conflicts between incoming candidate and existing active memories."""
        conflicts: List[Tuple[Memory, ConflictClass, str]] = []

        for existing in existing_memories:
            if existing.status != MemoryStatus.ACTIVE:
                continue
            if existing.memory_id == new_memory.memory_id:
                continue

            # T0: Exact key update (subject + predicate match, object differs)
            if (
                new_memory.type == MemoryType.FACT
                and existing.type == MemoryType.FACT
                and "subject" in new_memory.content_json
                and "subject" in existing.content_json
                and "predicate" in new_memory.content_json
                and "predicate" in existing.content_json
            ):
                if (
                    new_memory.content_json["subject"] == existing.content_json["subject"]
                    and new_memory.content_json["predicate"] == existing.content_json["predicate"]
                ):
                    if new_memory.content_json.get("object") != existing.content_json.get("object"):
                        conflicts.append(
                            (
                                existing,
                                ConflictClass.T0_EXACT_KEY_UPDATE,
                                f"Fact updated: {new_memory.content_json['subject']}.{new_memory.content_json['predicate']}",
                            )
                        )
                        continue

            # T1: Temporal supersession (decision / constraint explicit supersession)
            if (
                new_memory.type in (MemoryType.DECISION, MemoryType.CONSTRAINT)
                and existing.type == new_memory.type
                and new_memory.content_json.get("supersedes") == existing.memory_id
            ):
                conflicts.append(
                    (
                        existing,
                        ConflictClass.T1_TEMPORAL_SUPERSESSION,
                        f"Explicit supersession: {new_memory.memory_id} supersedes {existing.memory_id}",
                    )
                )
                continue

            # T2: Contradictory assumptions
            if (
                new_memory.type == MemoryType.ASSUMPTION
                and existing.type == MemoryType.ASSUMPTION
                and new_memory.content_json.get("topic")
                and new_memory.content_json.get("topic") == existing.content_json.get("topic")
                and new_memory.content_json.get("polarity") != existing.content_json.get("polarity")
            ):
                conflicts.append(
                    (
                        existing,
                        ConflictClass.T2_CONTRADICTORY_ASSUMPTIONS,
                        f"Contradictory assumptions on topic: {new_memory.content_json.get('topic')}",
                    )
                )
                continue

        return conflicts

    @staticmethod
    def apply_supersession(older: Memory, newer: Memory) -> None:
        """Mark older memory as superseded by newer memory."""
        older.status = MemoryStatus.SUPERSEDED
        older.superseded_by = newer.memory_id
        older.valid_to_event = newer.valid_from_event - 1
