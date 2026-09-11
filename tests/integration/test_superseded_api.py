"""IT2: Superseded API integration test.

Scenario:
Old API memory stored at version N.
API is changed and newer memory supersedes it at version N+5.
When a new agent is dispatched, the old memory must NEVER be delivered.
"""

import sqlite3
import pytest
from context.request import ContextRequest
from memory.conflicts import ConflictDetector
from memory.lifecycle import MemoryLifecycle
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)
from runtime.orchestrator import Orchestrator
from state.events import EventStore


def test_superseded_api_never_delivered(tmp_path):
    db_path = tmp_path / "superseded.db"
    store = EventStore(db_path)

    conn = sqlite3.connect(tmp_path / "mem.db")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    orch = Orchestrator(
        event_store=store,
        memory_lifecycle=lifecycle,
        repo_path=tmp_path,
        project_id="p_super",
    )
    orch.init_project(spec={"name": "test"})

    # 1. Store old API fact
    old_fact = Memory(
        memory_id="M_OLD_AUTH",
        project_id="p_super",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "AuthClient.login", "predicate": "return_type", "object": "Tuple[bool, str]"},
        content_text="AuthClient.login returns Tuple[bool, str]",
        created_event=1,
        valid_from_event=1,
        state_version_at_write=1,
        source_events=[1],
    )
    lifecycle.save_memory(old_fact)

    # 2. Store new superseding API fact
    new_fact = Memory(
        memory_id="M_NEW_AUTH",
        project_id="p_super",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "AuthClient.login", "predicate": "return_type", "object": "AuthResult"},
        content_text="AuthClient.login returns AuthResult",
        created_event=2,
        valid_from_event=2,
        state_version_at_write=2,
        source_events=[2],
    )
    ConflictDetector.apply_supersession(old_fact, new_fact)
    lifecycle.save_memory(old_fact)
    lifecycle.save_memory(new_fact)

    # 3. Request context for new task
    req = ContextRequest(
        context_request_id="CR_API_TEST",
        project_id="p_super",
        task_id="t_api",
        agent_id="agent_1",
        state_version=5,
        goal="Call AuthClient.login",
        token_budget=10000,
    )
    retrieval = orch.retriever.retrieve(req)
    packet = orch.compiler.compile(req, retrieval, orch.get_projection().project.state)

    # Invariant AC3: Verify M_OLD_AUTH is not included anywhere in compiled packet
    assert "M_OLD_AUTH" not in packet.memory_ids
    assert "M_NEW_AUTH" in packet.memory_ids

    store.close()
    conn.close()
