"""Memory Lifecycle Coordinator implementing creation, indexing, conflict handling, and retention."""

import json
import sqlite3
from typing import Dict, List, Optional, Set

from indexes.lexical import LexicalIndex
from indexes.relations import RelationIndex
from indexes.vector import VectorIndex
from memory.candidates import CandidateExtractor
from memory.conflicts import ConflictClass, ConflictDetector
from memory.consolidation import MemoryConsolidator
from memory.forgetting import MemoryForgettingEngine
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemorySource,
    MemoryStatus,
    MemoryType,
    SourceRole,
)
from memory.provenance import ProvenanceVerifier
from memory.write_gate import MemoryWriteGate
from state.models import Event


class MemoryLifecycle:
    """Coordinates memory lifecycle across candidate extraction, gating, conflicts, and indexing."""

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        write_threshold: float = 2.0,
    ) -> None:
        self._conn = db_conn
        self.write_gate = MemoryWriteGate(write_threshold)
        self.lexical_index = LexicalIndex(self._conn)
        self.vector_index = VectorIndex()
        self.relation_index = RelationIndex(self._conn)
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id              TEXT PRIMARY KEY,
                    project_id             TEXT NOT NULL,
                    type                   TEXT NOT NULL,
                    representation         TEXT NOT NULL,
                    content_json           TEXT NOT NULL,
                    content_text           TEXT,
                    created_event          INTEGER NOT NULL,
                    valid_from_event       INTEGER NOT NULL,
                    valid_to_event         INTEGER,
                    state_version_at_write INTEGER NOT NULL,
                    status                 TEXT NOT NULL,
                    superseded_by          TEXT,
                    confidence             REAL NOT NULL,
                    importance             REAL NOT NULL,
                    predicted_reuse        REAL NOT NULL,
                    access_count           INTEGER NOT NULL DEFAULT 0,
                    last_accessed_event    INTEGER,
                    token_size             INTEGER NOT NULL,
                    content_hash           TEXT NOT NULL,
                    producer_type          TEXT NOT NULL,
                    producer_model         TEXT,
                    producer_prompt_hash   TEXT,
                    source_events_json     TEXT NOT NULL,
                    tags_json              TEXT NOT NULL
                );
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_sources (
                    memory_id       TEXT NOT NULL,
                    source_event_id INTEGER NOT NULL,
                    source_role     TEXT NOT NULL,
                    PRIMARY KEY(memory_id, source_event_id)
                );
            """)

    def process_event(self, event: Event) -> List[str]:
        """Extract candidate memories from an event, evaluate write gate, resolve conflicts, and index."""
        candidates = CandidateExtractor.extract_from_event(event)
        created_ids: List[str] = []

        existing_active = self.get_active_memories(event.project_id, event.id)

        for cand in candidates:
            # Enforce Invariant I4 / I5
            ProvenanceVerifier.validate_memory(cand)

            # Evaluate write gate
            gate_breakdown = self.write_gate.evaluate(cand)
            if not gate_breakdown.passed:
                continue

            # Detect conflicts against active memories
            conflicts = ConflictDetector.detect_conflicts(cand, existing_active)
            for conflicting_mem, conflict_cls, reason in conflicts:
                if conflict_cls in (ConflictClass.T0_EXACT_KEY_UPDATE, ConflictClass.T1_TEMPORAL_SUPERSESSION):
                    ConflictDetector.apply_supersession(conflicting_mem, cand)
                    self.save_memory(conflicting_mem)
                elif conflict_cls == ConflictClass.T2_CONTRADICTORY_ASSUMPTIONS:
                    cand.status = MemoryStatus.DISPUTED
                    conflicting_mem.status = MemoryStatus.DISPUTED
                    self.save_memory(conflicting_mem)

            # Persist candidate
            self.save_memory(cand)
            self._index_memory(cand)
            created_ids.append(cand.memory_id)

        return created_ids

    def save_memory(self, memory: Memory) -> None:
        """Persist or update memory in SQLite."""
        ProvenanceVerifier.validate_memory(memory)
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memories (
                    memory_id, project_id, type, representation,
                    content_json, content_text, created_event, valid_from_event,
                    valid_to_event, state_version_at_write, status, superseded_by,
                    confidence, importance, predicted_reuse, access_count,
                    last_accessed_event, token_size, content_hash, producer_type,
                    producer_model, producer_prompt_hash, source_events_json, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id,
                    memory.project_id,
                    memory.type.value if hasattr(memory.type, "value") else str(memory.type),
                    memory.representation.value if hasattr(memory.representation, "value") else str(memory.representation),
                    json.dumps(memory.content_json),
                    memory.content_text,
                    memory.created_event,
                    memory.valid_from_event,
                    memory.valid_to_event,
                    memory.state_version_at_write,
                    memory.status.value if hasattr(memory.status, "value") else str(memory.status),
                    memory.superseded_by,
                    memory.confidence,
                    memory.importance,
                    memory.predicted_reuse,
                    memory.access_count,
                    memory.last_accessed_event,
                    memory.token_size,
                    memory.content_hash,
                    memory.producer_type,
                    memory.producer_model,
                    memory.producer_prompt_hash,
                    json.dumps(memory.source_events),
                    json.dumps(memory.tags),
                ),
            )

            # Persist source events
            for src_ev in memory.source_events:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_sources (memory_id, source_event_id, source_role)
                    VALUES (?, ?, ?)
                    """,
                    (memory.memory_id, src_ev, SourceRole.DERIVED_FROM.value),
                )

    def _index_memory(self, memory: Memory) -> None:
        if memory.status == MemoryStatus.ACTIVE:
            self.lexical_index.index_document(
                memory.memory_id,
                title=f"{memory.type} - {memory.memory_id}",
                content=memory.content_text,
                tags=" ".join(memory.tags),
            )
            vec = VectorIndex.mock_embed_text(memory.content_text)
            self.vector_index.add_vector(memory.memory_id, vec)
        else:
            self.vector_index.remove(memory.memory_id)

    def get_memory(self, memory_id: str) -> Optional[Memory]:
        cursor = self._conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_memory(row)

    def get_active_memories(self, project_id: str, state_version: Optional[int] = None) -> List[Memory]:
        """Fetch active memories valid at specified state version."""
        cursor = self._conn.execute(
            "SELECT * FROM memories WHERE project_id = ? AND status = 'active' ORDER BY created_event ASC",
            (project_id,),
        )
        memories = [self._row_to_memory(r) for r in cursor.fetchall()]
        if state_version is not None:
            memories = [m for m in memories if ProvenanceVerifier.is_valid_at_version(m, state_version)]
        return memories

    def consolidate(self, *, project_id: str, upto_event: int) -> List[str]:
        """Consolidate recurring failures into reusable procedures."""
        cursor = self._conn.execute(
            """
            SELECT * FROM memories
            WHERE project_id = ? AND type = 'failure' AND status = 'active' AND created_event <= ?
            """,
            (project_id, upto_event),
        )
        failures = [self._row_to_memory(r) for r in cursor.fetchall()]
        consolidated = MemoryConsolidator.consolidate_failures(failures, project_id, upto_event)
        if consolidated:
            self.save_memory(consolidated)
            self._index_memory(consolidated)
            return [consolidated.memory_id]
        return []

    def archive_low_value(self, *, project_id: str, upto_event: int) -> List[str]:
        """Archive low keep-score memories."""
        active = self.get_active_memories(project_id, upto_event)
        archived = MemoryForgettingEngine.archive_low_value(active, upto_event, active_task_tags=set())
        for mem in archived:
            self.save_memory(mem)
            self.vector_index.remove(mem.memory_id)
        return [m.memory_id for m in archived]

    def rebuild_indexes_from_memories(self) -> None:
        """Invariant I3: Derived stores must be rebuildable."""
        self.lexical_index.clear()
        self.vector_index.clear()
        cursor = self._conn.execute("SELECT * FROM memories WHERE status = 'active'")
        for row in cursor.fetchall():
            mem = self._row_to_memory(row)
            self._index_memory(mem)

    def clear_all(self) -> None:
        """Clear all memory tables and indexes."""
        with self._conn:
            self._conn.execute("DELETE FROM memories;")
            self._conn.execute("DELETE FROM memory_sources;")
            self._conn.execute("DELETE FROM memory_relations;")
        self.lexical_index.clear()
        self.vector_index.clear()

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        return Memory(
            memory_id=row["memory_id"],
            project_id=row["project_id"],
            type=MemoryType(row["type"]),
            representation=MemoryRepresentation(row["representation"]),
            content_json=json.loads(row["content_json"]),
            content_text=row["content_text"] or "",
            created_event=row["created_event"],
            valid_from_event=row["valid_from_event"],
            valid_to_event=row["valid_to_event"],
            state_version_at_write=row["state_version_at_write"],
            status=MemoryStatus(row["status"]),
            superseded_by=row["superseded_by"],
            confidence=row["confidence"],
            importance=row["importance"],
            predicted_reuse=row["predicted_reuse"],
            access_count=row["access_count"],
            last_accessed_event=row["last_accessed_event"],
            token_size=row["token_size"],
            content_hash=row["content_hash"],
            producer_type=row["producer_type"],
            producer_model=row["producer_model"],
            producer_prompt_hash=row["producer_prompt_hash"],
            source_events=json.loads(row["source_events_json"]),
            tags=json.loads(row["tags_json"]),
        )
