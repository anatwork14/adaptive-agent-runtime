"""Unit tests for Context Control Plane and ContextCompiler."""

import sqlite3
from context.allocator import BudgetAllocator
from context.compiler import ContextCompiler
from context.digest import compute_context_digest
from context.request import ContextRequest
from context.retrieval import MemoryRetriever
from context.staleness import StalenessDetector
from memory.lifecycle import MemoryLifecycle
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)
from state.events import EventStore
from state.models import PatchSubmission, ProjectState, TaskState


def test_context_digest_stability():
    packet1 = {
        "context_id": "CTX_1",
        "project_id": "p1",
        "task_id": "t1",
        "state_version": 100,
        "goal": "Test goal",
        "decisions": [{"id": "d1"}],
    }
    packet2 = {
        "decisions": [{"id": "d1"}],
        "goal": "Test goal",
        "task_id": "t1",
        "state_version": 100,
        "project_id": "p1",
        "context_id": "CTX_1",
    }
    d1 = compute_context_digest(packet1)
    d2 = compute_context_digest(packet2)
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_context_compiler_budget_and_authoritative_core(tmp_path):
    store = EventStore(tmp_path / "ctx_store.db")
    store.append(actor="orch", kind="project.created", project_id="p1", payload={"constraints": ["no-internet"]})

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    # Active decision
    m_dec = Memory(
        memory_id="M_DEC_1",
        project_id="p1",
        type=MemoryType.DECISION,
        representation=MemoryRepresentation.DECISION_RECORD,
        content_json={"decision": "Use SQLite WAL mode"},
        content_text="Use SQLite WAL mode for concurrency",
        created_event=1,
        valid_from_event=1,
        state_version_at_write=1,
        token_size=20,
        source_events=[1],
        tags=["sqlite", "wal"],
    )
    lifecycle.save_memory(m_dec)

    retriever = MemoryRetriever(lifecycle)
    compiler = ContextCompiler(store)

    req = ContextRequest(
        context_request_id="CR_1",
        project_id="p1",
        task_id="t1",
        agent_id="agent_codex",
        state_version=1,
        goal="Implement persistence layer",
        token_budget=10000,
    )

    retrieval_res = retriever.retrieve(req)
    proj_state = ProjectState(project_id="p1", constraints=["no-internet"])
    task_state = TaskState(task_id="t1", project_id="p1", goal="Implement persistence layer", acceptance_criteria=["Tests pass"])

    packet = compiler.compile(req, retrieval_res, proj_state, task_state)

    # Assertions
    assert packet.context_token_count <= req.token_budget  # AC4
    assert packet.goal == "Implement persistence layer"  # C0 Core
    assert "no-internet" in packet.constraints  # C0 Core
    assert "Tests pass" in packet.acceptance_criteria  # C0 Core
    assert len(packet.decisions) == 1
    assert packet.decisions[0]["memory_id"] == "M_DEC_1"
    assert packet.digest.startswith("sha256:")

    store.close()


def test_superseded_memory_never_packed(tmp_path):
    store = EventStore(tmp_path / "supersede_test.db")
    store.append(actor="orch", kind="project.created", project_id="p1", payload={})

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    # Memory 1: Superseded
    m_old = Memory(
        memory_id="M_OLD",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "api", "predicate": "version", "object": "v1"},
        content_text="API version is v1",
        created_event=1,
        valid_from_event=1,
        valid_to_event=2,
        state_version_at_write=1,
        status=MemoryStatus.SUPERSEDED,
        superseded_by="M_NEW",
        source_events=[1],
    )
    lifecycle.save_memory(m_old)

    # Memory 2: Active
    m_new = Memory(
        memory_id="M_NEW",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"subject": "api", "predicate": "version", "object": "v2"},
        content_text="API version is v2",
        created_event=3,
        valid_from_event=3,
        state_version_at_write=3,
        status=MemoryStatus.ACTIVE,
        source_events=[3],
    )
    lifecycle.save_memory(m_new)

    retriever = MemoryRetriever(lifecycle)
    compiler = ContextCompiler(store)

    req = ContextRequest(
        context_request_id="CR_2",
        project_id="p1",
        task_id="t2",
        agent_id="agent_1",
        state_version=5,
        goal="Call the API",
    )

    retrieval_res = retriever.retrieve(req)
    proj_state = ProjectState(project_id="p1")

    packet = compiler.compile(req, retrieval_res, proj_state)

    # Invariant AC3: M_OLD must NOT be in memory_ids or anywhere in packet
    assert "M_OLD" not in packet.memory_ids

    store.close()


def test_staleness_detector_identifies_intervening_changes(tmp_path):
    store = EventStore(tmp_path / "stale_detector.db")
    store.append(actor="orch", kind="project.created", project_id="p1", payload={})
    store.append(actor="orch", kind="task.created", project_id="p1", task_id="t1", payload={})
    store.append(actor="orch", kind="task.dispatched", project_id="p1", task_id="t1", payload={"state_version": 2})

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    detector = StalenessDetector(store, lifecycle)

    # Submission at dispatch_version 3 (current version) with no subsequent events
    sub_clean = PatchSubmission(
        patch_id="p_clean",
        task_id="t1",
        agent_id="a1",
        context_id="ctx_1",
        dispatch_state_version=3,
        diff="clean",
    )
    assessment_clean = detector.evaluate_submission(sub_clean, "p1", dependency_task_ids=set(), declared_files=set())
    assert assessment_clean.is_stale is False
    assert assessment_clean.staleness_score == 0.0

    # Add 5 events modifying dependency and declared files
    for i in range(5):
        store.append(
            actor="orch",
            kind="task.updated",
            project_id="p1",
            task_id="dep_task",
            payload={"files": ["src/core.py"]},
        )

    assessment_stale = detector.evaluate_submission(
        sub_clean,
        "p1",
        dependency_task_ids={"dep_task"},
        declared_files={"src/core.py"},
    )
    # AC6: Injected stale changes must be detected
    assert assessment_stale.delta_events_count == 5
    assert assessment_stale.relevant_delta_events > 0
    assert assessment_stale.requires_revalidation is True

    store.close()
