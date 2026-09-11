"""Memory lifecycle coordinator with replayable materialized memory events."""

import json
import sqlite3
from typing import List, Optional

from indexes.lexical import LexicalIndex
from indexes.relations import RelationIndex
from indexes.vector import VectorIndex
from memory.candidates import CandidateExtractor
from memory.conflicts import ConflictClass, ConflictDetector
from memory.consolidation import MemoryConsolidator
from memory.forgetting import MemoryForgettingEngine
from memory.models import Memory, MemoryRepresentation, MemoryStatus, MemoryType, SourceRole
from memory.provenance import ProvenanceVerifier
from memory.write_gate import MemoryWriteGate
from state.events import EventStore
from state.models import Event


class MemoryLifecycle:
    """Coordinate derived memory while keeping the event log authoritative.

    Every persisted memory mutation can be emitted as ``memory.materialized``.
    Rebuilding memory from history replays those materialized outputs rather
    than re-running an LLM or a summarizer, which preserves reproducibility.
    """

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        write_threshold: float = 2.0,
        event_store: Optional[EventStore] = None,
    ) -> None:
        self._conn = db_conn
        self.event_store = event_store
        self.write_gate = MemoryWriteGate(write_threshold)
        self.lexical_index = LexicalIndex(self._conn)
        self.vector_index = VectorIndex()
        self.relation_index = RelationIndex(self._conn)
        self._init_tables()

    def bind_event_store(self, event_store: EventStore) -> None:
        """Attach the authoritative event store used for materialization events."""
        self.event_store = event_store

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.execute(
                """
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
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_sources (
                    memory_id       TEXT NOT NULL,
                    source_event_id INTEGER NOT NULL,
                    source_role     TEXT NOT NULL,
                    PRIMARY KEY(memory_id, source_event_id)
                );
                """
            )

    def process_event(self, event: Event) -> List[str]:
        """Project an authoritative event into the adaptive memory plane."""
        if event.kind == "memory.materialized":
            raw = event.payload.get("memory")
            if not isinstance(raw, dict):
                return []
            memory = Memory.model_validate(raw)
            self.save_memory(memory, emit_event=False)
            return [memory.memory_id]

        candidates = CandidateExtractor.extract_from_event(event)
        created_ids: List[str] = []
        existing_active = self.get_active_memories(event.project_id, event.id)

        for candidate in candidates:
            ProvenanceVerifier.validate_memory(candidate)
            if not self.write_gate.evaluate(candidate).passed:
                continue

            conflicts = ConflictDetector.detect_conflicts(candidate, existing_active)
            for conflicting_mem, conflict_cls, _reason in conflicts:
                if conflict_cls in (
                    ConflictClass.T0_EXACT_KEY_UPDATE,
                    ConflictClass.T1_TEMPORAL_SUPERSESSION,
                ):
                    ConflictDetector.apply_supersession(conflicting_mem, candidate)
                    self.save_memory(conflicting_mem, emit_event=True)
                elif conflict_cls == ConflictClass.T2_CONTRADICTORY_ASSUMPTIONS:
                    candidate.status = MemoryStatus.DISPUTED
                    conflicting_mem.status = MemoryStatus.DISPUTED
                    self.save_memory(conflicting_mem, emit_event=True)

            self.save_memory(candidate, emit_event=True)
            created_ids.append(candidate.memory_id)
            existing_active.append(candidate)

        return created_ids

    def save_memory(self, memory: Memory, *, emit_event: bool = True) -> None:
        """Persist a memory projection and optionally materialize it in the event log."""
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
                    memory.type.value,
                    memory.representation.value,
                    json.dumps(memory.content_json, sort_keys=True),
                    memory.content_text,
                    memory.created_event,
                    memory.valid_from_event,
                    memory.valid_to_event,
                    memory.state_version_at_write,
                    memory.status.value,
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
            for source_event_id in memory.source_events:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO memory_sources
                    (memory_id, source_event_id, source_role)
                    VALUES (?, ?, ?)
                    """,
                    (memory.memory_id, source_event_id, SourceRole.DERIVED_FROM.value),
                )

        self._index_memory(memory)

        if emit_event and self.event_store is not None:
            self.event_store.append(
                actor="memory",
                kind="memory.materialized",
                project_id=memory.project_id,
                payload={
                    "memory_id": memory.memory_id,
                    "memory": memory.model_dump(mode="json"),
                },
                causation_id=max(memory.source_events) if memory.source_events else None,
            )

    def _index_memory(self, memory: Memory) -> None:
        if memory.status == MemoryStatus.ACTIVE:
            self.lexical_index.index_document(
                memory.memory_id,
                title=f"{memory.type.value} - {memory.memory_id}",
                content=memory.content_text,
                tags=" ".join(memory.tags),
            )
            vector = VectorIndex.deterministic_hash_embed(
                memory.content_text,
                dimension=self.vector_index.dimension,
            )
            self.vector_index.add_vector(memory.memory_id, vector)
        else:
            self.vector_index.remove(memory.memory_id)

    def get_memory(self, memory_id: str) -> Optional[Memory]:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_memory(row) if row else None

    def get_active_memories(
        self,
        project_id: str,
        state_version: Optional[int] = None,
    ) -> List[Memory]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE project_id = ? AND status = 'active' "
            "ORDER BY created_event ASC",
            (project_id,),
        ).fetchall()
        memories = [self._row_to_memory(row) for row in rows]
        if state_version is not None:
            memories = [
                memory
                for memory in memories
                if ProvenanceVerifier.is_valid_at_version(memory, state_version)
            ]
        return memories

    def consolidate(self, *, project_id: str, upto_event: int) -> List[str]:
        rows = self._conn.execute(
            """
            SELECT * FROM memories
            WHERE project_id = ? AND type = 'failure'
              AND status = 'active' AND created_event <= ?
            """,
            (project_id, upto_event),
        ).fetchall()
        failures = [self._row_to_memory(row) for row in rows]
        consolidated = MemoryConsolidator.consolidate_failures(
            failures, project_id, upto_event
        )
        if not consolidated:
            return []
        self.save_memory(consolidated, emit_event=True)
        return [consolidated.memory_id]

    def archive_low_value(self, *, project_id: str, upto_event: int) -> List[str]:
        active = self.get_active_memories(project_id, upto_event)
        archived = MemoryForgettingEngine.archive_low_value(
            active, upto_event, active_task_tags=set()
        )
        for memory in archived:
            self.save_memory(memory, emit_event=True)
        return [memory.memory_id for memory in archived]

    def rebuild_from_events(self, events: List[Event], *, project_id: str) -> List[str]:
        """Rebuild memory strictly from recorded materialization events.

        This deliberately does not call CandidateExtractor or any model. It is
        the deterministic recovery path after deleting derived memory storage.
        """
        self.clear_all()
        restored: List[str] = []
        for event in events:
            if event.project_id == project_id and event.kind == "memory.materialized":
                restored.extend(self.process_event(event))
        return restored

    def rebuild_indexes_from_memories(self) -> None:
        self.lexical_index.clear()
        self.vector_index.clear()
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE status = 'active'"
        ).fetchall()
        for row in rows:
            self._index_memory(self._row_to_memory(row))

    def clear_all(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM memories")
            self._conn.execute("DELETE FROM memory_sources")
            # RelationIndex owns this table, but clearing it is part of rebuilding
            # the derived memory plane.
            try:
                self._conn.execute("DELETE FROM memory_relations")
            except sqlite3.OperationalError:
                pass
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
