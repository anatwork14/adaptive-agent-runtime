"""IT6: Memory Archival and Hard-Retention integration test.

Scenario:
Archive old low-value memories (episodes, transient summaries).
Verify that critical architectural decisions and procedures remain retrievable.
"""

import sqlite3

from memory.lifecycle import MemoryLifecycle
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)


def test_archive_preserves_hard_retain_decisions():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    # 1. Critical decision (Hard-retain class)
    m_dec = Memory(
        memory_id="M_CRITICAL_DEC",
        project_id="p_arch",
        type=MemoryType.DECISION,
        representation=MemoryRepresentation.DECISION_RECORD,
        content_json={"decision": "Never store secrets in memory"},
        content_text="Never store secrets in memory",
        created_event=10,
        valid_from_event=10,
        state_version_at_write=10,
        status=MemoryStatus.ACTIVE,
        confidence=1.0,
        importance=0.99,
        source_events=[10],
    )
    lifecycle.save_memory(m_dec)

    # 2. Transient episode memory from event 10
    m_ep = Memory(
        memory_id="M_OLD_EPISODE",
        project_id="p_arch",
        type=MemoryType.EPISODE,
        representation=MemoryRepresentation.SUMMARY,
        content_json={"note": "Agent tried reading foo.txt"},
        content_text="Agent tried reading foo.txt",
        created_event=10,
        valid_from_event=10,
        state_version_at_write=10,
        status=MemoryStatus.ACTIVE,
        confidence=0.5,
        importance=0.1,
        predicted_reuse=0.0,
        source_events=[10],
    )
    lifecycle.save_memory(m_ep)

    # Fast-forward to event 3000 and run archival
    archived = lifecycle.archive_low_value(project_id="p_arch", upto_event=3000)

    assert "M_OLD_EPISODE" in archived
    assert "M_CRITICAL_DEC" not in archived

    # Check active memories at event 3000
    active = lifecycle.get_active_memories("p_arch", state_version=3000)
    active_ids = [m.memory_id for m in active]
    assert "M_CRITICAL_DEC" in active_ids
    assert "M_OLD_EPISODE" not in active_ids

    conn.close()
