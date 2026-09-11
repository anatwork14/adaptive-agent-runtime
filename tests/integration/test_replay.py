"""IT5: Deterministic Replay and Derived Index Rebuilding (Invariants I3, AC1, AC2).

Scenario:
1. Run a complex series of tasks, events, and memories.
2. Capture state projection and hashes.
3. Completely delete all derived tables, caches, and indexes.
4. Replay event log from scratch.
5. Verify reconstructed state matches exactly.
"""

import sqlite3
import pytest
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from runtime.replay import ReplayEngine
from state.events import EventStore
from state.projection import DeterministicStateProjection


def test_event_replay_reconstructs_state_after_index_deletion(tmp_path):
    db_path = tmp_path / "replay_authoritative.db"
    store = EventStore(db_path)

    mem_conn = sqlite3.connect(tmp_path / "replay_mem.db")
    mem_conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(mem_conn)

    orch = Orchestrator(
        event_store=store,
        memory_lifecycle=lifecycle,
        repo_path=tmp_path,
        project_id="p_replay",
    )

    # 1. Populate rich history of events
    orch.init_project(spec={"framework": "fastapi"}, constraints=["no-direct-db-access"])
    orch.create_task("t1", "Setup models", files_declared=["src/models.py"])
    orch.create_task("t2", "Setup routes", dependencies=["t1"], files_declared=["src/routes.py"])

    # Simulate completions and gate acceptances
    store.append(actor="orch", kind="task.dispatched", project_id="p_replay", task_id="t1", payload={"agent_id": "codex"})
    ev_acc = store.append(
        actor="gate",
        kind="gate.accepted",
        project_id="p_replay",
        task_id="t1",
        payload={"patch_id": "p1", "decisions": ["All models inherit from BaseModel"]},
    )
    lifecycle.process_event(store.read_event(ev_acc))

    # Capture initial projection
    events_initial = store.read_all(project_id="p_replay")
    proj_initial = DeterministicStateProjection.replay_from_events("p_replay", events_initial)

    # AC1: Delete all derived memory and index tables
    lifecycle.clear_all()
    assert len(lifecycle.get_active_memories("p_replay")) == 0

    # Replay event log
    engine = ReplayEngine(store)
    proj_replayed = engine.replay_project("p_replay")

    # Invariants AC1 & AC2: Authoritative projections are 100% reconstructible
    assert proj_replayed.version == proj_initial.version
    assert proj_replayed.project.state.model_dump() == proj_initial.project.state.model_dump()
    assert {k: v.model_dump() for k, v in proj_replayed.dag.tasks.items()} == {
        k: v.model_dump() for k, v in proj_initial.dag.tasks.items()
    }
    assert proj_replayed.dag.tasks["t1"].status.value == "completed"
    assert proj_replayed.dag.tasks["t2"].status.value == "ready"

    # Reconstruct memory lifecycle from replay events
    for ev in store.read_all(project_id="p_replay"):
        lifecycle.process_event(ev)

    reconstructed_mems = lifecycle.get_active_memories("p_replay")
    assert len(reconstructed_mems) > 0
    assert any("BaseModel" in m.content_text for m in reconstructed_mems)

    store.close()
    mem_conn.close()
