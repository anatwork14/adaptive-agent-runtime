"""IT3: Concurrent dependency change integration test.

Scenario:
Agent A dispatched at state version N.
Concurrently, another agent merges relevant interface changes (versions N+1 .. N+5).
Agent A patch submission is evaluated.
Staleness detector must flag the submission as stale / requiring revalidation.
"""

import sqlite3

from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore
from state.models import PatchSubmission


def test_concurrent_dependency_change_detected_as_stale(tmp_path):
    db_path = tmp_path / "concurrent.db"
    store = EventStore(db_path)

    conn = sqlite3.connect(tmp_path / "mem.db")
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    orch = Orchestrator(
        event_store=store,
        memory_lifecycle=lifecycle,
        repo_path=tmp_path,
        project_id="p_concurrent",
    )
    orch.init_project(spec={"name": "concurrent_test"})
    orch.create_task("t_dep", "Base dependency task", files_declared=["src/base.py"])
    orch.create_task("t_agent_a", "Subtask depending on base", dependencies=["t_dep"], files_declared=["src/feature.py"])

    # Agent A dispatched at version 3
    dispatch_v = store.current_version("p_concurrent")

    # While Agent A is running, 4 events occur touching dependency t_dep and src/base.py
    for i in range(4):
        store.append(
            actor="agent_b",
            kind="task.updated",
            project_id="p_concurrent",
            task_id="t_dep",
            payload={"files": ["src/base.py"], "change": f"update {i}"},
        )

    # Agent A now submits patch referencing dispatch_v
    submission = PatchSubmission(
        patch_id="patch_a",
        task_id="t_agent_a",
        agent_id="agent_a",
        context_id="ctx_a",
        dispatch_state_version=dispatch_v,
        diff="def use_base(): pass",
    )

    assessment = orch.staleness_detector.evaluate_submission(
        submission=submission,
        project_id="p_concurrent",
        dependency_task_ids={"t_dep"},
        declared_files={"src/feature.py"},
    )

    # Invariant AC6: Stale context detected
    assert assessment.requires_revalidation is True
    assert assessment.dependency_change_count > 0
    assert assessment.delta_events_count == 4

    store.close()
    conn.close()
