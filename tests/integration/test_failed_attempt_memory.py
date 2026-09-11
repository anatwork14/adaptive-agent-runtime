"""IT4: Failed attempt memory integration test.

Scenario:
Attempt 1 fails due to a missing dependency / schema error.
Gate records failure and candidate extractor stores failure memory.
Attempt 2 context compilation includes the failure memory in C4 class.
"""

import sqlite3
import pytest
from context.request import ContextRequest
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore
from state.models import PatchSubmission


def test_failed_attempt_generates_retrievable_memory(tmp_path):
    db_path = tmp_path / "failed_attempt.db"
    store = EventStore(db_path)

    conn = sqlite3.connect(tmp_path / "mem.db")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    orch = Orchestrator(
        event_store=store,
        memory_lifecycle=lifecycle,
        repo_path=tmp_path,
        project_id="p_fail",
    )
    orch.init_project(spec={"name": "fail_test"})
    orch.create_task("t_fail", "Migrate database schema", files_declared=["migrations/001.sql"])

    # Simulate attempt 1 failure event
    ev_id = store.append(
        actor="gate",
        kind="gate.c1_failed",
        project_id="p_fail",
        task_id="t_fail",
        payload={"error": "Migration failed: table users already exists", "rejection_stage": "G1"},
    )

    # Process event in lifecycle
    failed_ev = store.read_event(ev_id)
    created_ids = lifecycle.process_event(failed_ev)
    assert len(created_ids) > 0

    # Compile context for Attempt 2
    req = ContextRequest(
        context_request_id="CR_ATTEMPT_2",
        project_id="p_fail",
        task_id="t_fail",
        agent_id="agent_retry",
        state_version=ev_id,
        goal="Migrate database schema",
        token_budget=10000,
    )
    retrieval = orch.retriever.retrieve(req)
    packet = orch.compiler.compile(req, retrieval, orch.get_projection().project.state)

    # Attempt 2 must receive useful failure context (C4)
    assert len(packet.failures) > 0
    assert "users already exists" in packet.failures[0]["text"]

    store.close()
    conn.close()
