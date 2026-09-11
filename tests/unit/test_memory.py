"""Unit tests for the Adaptive Memory Plane."""

import sqlite3
import pytest
from memory.conflicts import ConflictClass, ConflictDetector
from memory.lifecycle import MemoryLifecycle
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)
from memory.provenance import ProvenanceVerifier
from state.models import Event


def test_memory_without_source_event_rejected():
    mem = Memory(
        memory_id="M_NO_SRC",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "Auth", "predicate": "enabled", "object": True},
        created_event=10,
        valid_from_event=10,
        state_version_at_write=10,
        source_events=[],  # Empty!
    )
    with pytest.raises(ValueError, match="Invariant I4 violated"):
        ProvenanceVerifier.validate_memory(mem)


def test_temporal_validity_and_supersession(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    # Event 1: Initial fact
    fact1 = Memory(
        memory_id="M_API_1",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "AuthClient.login", "predicate": "return_type", "object": "Result[Token]"},
        content_text="AuthClient.login returns Result[Token]",
        created_event=100,
        valid_from_event=100,
        state_version_at_write=100,
        source_events=[100],
    )
    lifecycle.save_memory(fact1)

    # Verify fact1 is active at version 150
    active_150 = lifecycle.get_active_memories("p1", state_version=150)
    assert len(active_150) == 1
    assert active_150[0].memory_id == "M_API_1"

    # Event 2: Updated fact at version 200 (T0 Conflict)
    fact2 = Memory(
        memory_id="M_API_2",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "AuthClient.login", "predicate": "return_type", "object": "AuthResult"},
        content_text="AuthClient.login returns AuthResult",
        created_event=200,
        valid_from_event=200,
        state_version_at_write=200,
        source_events=[200],
    )

    ev = Event(
        id=200,
        actor="orch",
        kind="project.spec_updated",
        project_id="p1",
        content_hash="abc",
    )
    # Manually check conflict & supersession
    conflicts = ConflictDetector.detect_conflicts(fact2, [fact1])
    assert len(conflicts) == 1
    assert conflicts[0][1] == ConflictClass.T0_EXACT_KEY_UPDATE

    ConflictDetector.apply_supersession(fact1, fact2)
    lifecycle.save_memory(fact1)
    lifecycle.save_memory(fact2)

    # At state version 250, only fact2 is active; fact1 is superseded
    active_250 = lifecycle.get_active_memories("p1", state_version=250)
    active_ids = [m.memory_id for m in active_250]
    assert "M_API_2" in active_ids
    assert "M_API_1" not in active_ids

    # Inspect fact1
    stored_fact1 = lifecycle.get_memory("M_API_1")
    assert stored_fact1.status == MemoryStatus.SUPERSEDED
    assert stored_fact1.superseded_by == "M_API_2"
    assert stored_fact1.valid_to_event == 199


def test_contradictory_assumptions_marked_disputed():
    a1 = Memory(
        memory_id="M_ASSUME_1",
        project_id="p1",
        type=MemoryType.ASSUMPTION,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"topic": "external_callers", "polarity": False},
        created_event=10,
        valid_from_event=10,
        state_version_at_write=10,
        source_events=[10],
    )
    a2 = Memory(
        memory_id="M_ASSUME_2",
        project_id="p1",
        type=MemoryType.ASSUMPTION,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"topic": "external_callers", "polarity": True},
        created_event=20,
        valid_from_event=20,
        state_version_at_write=20,
        source_events=[20],
    )

    conflicts = ConflictDetector.detect_conflicts(a2, [a1])
    assert len(conflicts) == 1
    assert conflicts[0][1] == ConflictClass.T2_CONTRADICTORY_ASSUMPTIONS
