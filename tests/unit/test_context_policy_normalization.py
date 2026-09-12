"""Unit regressions for normalized B3/B5/B7 context policies."""

from __future__ import annotations

import sqlite3

from context.compiler import ContextCompiler
from context.digest import compute_context_digest
from context.policy import RuntimeContextPolicy
from context.request import ContextRequest
from context.retrieval import MemoryRetriever, RetrievalResult
from eval.baselines.normalized import StaticStructuredContextPolicy, VectorTopKContextPolicy
from memory.lifecycle import MemoryLifecycle
from memory.models import Memory, MemoryRepresentation, MemoryStatus, MemoryType
from state.events import EventStore
from state.models import ProjectState, TaskState



def _state() -> tuple[ProjectState, TaskState]:
    return (
        ProjectState(project_id="p1", constraints=["preserve-api"]),
        TaskState(
            task_id="T001",
            project_id="p1",
            goal="use legacy api v1 safely",
            acceptance_criteria=["tests pass"],
            token_budget=8000,
        ),
    )



def test_compiled_packet_digest_matches_final_immutable_packet(tmp_path) -> None:
    store = EventStore(tmp_path / "digest.db")
    store.append(actor="orch", kind="project.created", project_id="p1", payload={})
    compiler = ContextCompiler(store)
    project, task = _state()
    request = ContextRequest(
        context_request_id="CR_digest",
        project_id="p1",
        task_id=task.task_id,
        agent_id="mock",
        state_version=store.current_version("p1"),
        goal=task.goal,
        token_budget=task.token_budget,
    )

    packet = compiler.compile(request, RetrievalResult(), project, task)

    assert packet.compiled_event > request.state_version
    assert packet.digest == compute_context_digest(packet.model_dump(mode="json"))
    store.close()



def test_b3_b5_b7_change_only_context_selection_semantics(tmp_path) -> None:
    store = EventStore(tmp_path / "policy.db")
    store.append(actor="orch", kind="project.created", project_id="p1", payload={})

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn, event_store=store)

    stale = Memory(
        memory_id="M_STALE",
        project_id="p1",
        type=MemoryType.FACT,
        representation=MemoryRepresentation.STRUCTURED_FACT,
        content_json={"api": "v1"},
        content_text="legacy api v1 legacy api v1",
        created_event=1,
        valid_from_event=1,
        valid_to_event=1,
        state_version_at_write=1,
        status=MemoryStatus.SUPERSEDED,
        superseded_by="M_NEW",
        token_size=8,
        source_events=[1],
    )
    lifecycle.save_memory(stale, emit_event=True)

    project, task = _state()
    request = ContextRequest(
        context_request_id="CR_policy",
        project_id="p1",
        task_id=task.task_id,
        agent_id="mock",
        state_version=store.current_version("p1"),
        goal=task.goal,
        token_budget=task.token_budget,
    )
    compiler = ContextCompiler(store)

    b3 = StaticStructuredContextPolicy(compiler).build(
        request=request,
        project_state=project,
        task_state=task,
        active_leases=[],
    )
    b5 = VectorTopKContextPolicy(compiler, lifecycle, top_k=5).build(
        request=request,
        project_state=project,
        task_state=task,
        active_leases=[],
    )
    b7 = RuntimeContextPolicy(MemoryRetriever(lifecycle), compiler).build(
        request=request,
        project_state=project,
        task_state=task,
        active_leases=[],
    )

    assert b3.packet.context_policy == "B3"
    assert b3.packet.memory_ids == []
    assert b3.packet.stale_memory_ids == []
    assert b3.retrieval_strategies == ("static_no_memory",)

    assert b5.packet.context_policy == "B5"
    assert "M_STALE" in b5.packet.memory_ids
    assert "M_STALE" in b5.packet.stale_memory_ids
    assert "STALE_MEMORY_DELIVERED" in b5.packet.risk_flags
    assert b5.retrieval_strategies == ("naive_vector_topk:k=5",)

    assert b7.packet.context_policy == "B7"
    assert "M_STALE" not in b7.packet.memory_ids
    assert b7.packet.stale_memory_ids == []

    for build in (b3, b5, b7):
        assert build.packet.context_token_count <= task.token_budget
        assert build.packet.goal == task.goal
        assert build.packet.acceptance_criteria == task.acceptance_criteria
        assert build.retrieval_latency_ms >= 0.0
        assert build.compile_latency_ms >= 0.0

    store.close()
    conn.close()
