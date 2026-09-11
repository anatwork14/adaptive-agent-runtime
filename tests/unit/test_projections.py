"""Unit tests for deterministic state projections."""

from state.events import EventStore
from state.models import TaskStatus
from state.projection import DeterministicStateProjection


def test_state_projections_and_task_dag(tmp_path):
    store = EventStore(tmp_path / "proj.db")

    store.append(
        actor="orch",
        kind="project.created",
        project_id="p_proj",
        payload={"spec": {"title": "Test Project"}, "constraints": ["no-network"]},
    )
    store.append(
        actor="orch",
        kind="task.created",
        project_id="p_proj",
        task_id="t1",
        payload={"goal": "Build foundation", "dependencies": []},
    )
    store.append(
        actor="orch",
        kind="task.created",
        project_id="p_proj",
        task_id="t2",
        payload={"goal": "Build on foundation", "dependencies": ["t1"]},
    )

    events = store.read_all(project_id="p_proj")
    proj = DeterministicStateProjection.replay_from_events("p_proj", events)

    assert proj.project.state.status == "active"
    assert "no-network" in proj.project.state.constraints
    assert proj.dag.tasks["t1"].status == TaskStatus.READY
    assert proj.dag.tasks["t2"].status == TaskStatus.CREATED

    # Now dispatch t1
    store.append(
        actor="orch",
        kind="task.dispatched",
        project_id="p_proj",
        task_id="t1",
        payload={"agent_id": "codex_1", "state_version": 2},
    )
    # Complete t1
    store.append(
        actor="orch",
        kind="gate.accepted",
        project_id="p_proj",
        task_id="t1",
        payload={"patch_id": "patch_1"},
    )

    events = store.read_all(project_id="p_proj")
    proj2 = DeterministicStateProjection.replay_from_events("p_proj", events)

    assert proj2.dag.tasks["t1"].status == TaskStatus.COMPLETED
    assert proj2.dag.tasks["t2"].status == TaskStatus.READY
    assert "t1" in proj2.project.state.completed_tasks

    store.close()


def test_lease_and_budget_projection(tmp_path):
    store = EventStore(tmp_path / "lease_budget.db")
    store.append(
        actor="orch",
        kind="lease.granted",
        project_id="p1",
        task_id="t1",
        payload={"resource": "src/auth/**", "holder": "agent_1"},
        fencing_token=42,
    )
    store.append(
        actor="orch",
        kind="budget.consumed",
        project_id="p1",
        task_id="t1",
        payload={"usd": 0.25, "tokens": 1200},
    )

    events = store.read_all(project_id="p1")
    proj = DeterministicStateProjection.replay_from_events("p1", events)

    lease = proj.leases.get_active_lease("src/auth/**")
    assert lease is not None
    assert lease.fencing_token == 42
    assert lease.holder == "agent_1"

    assert proj.budgets.state.consumed_usd == 0.25
    assert proj.budgets.state.consumed_tokens == 1200
    assert proj.budgets.state.per_task_consumed_usd["t1"] == 0.25

    # Release lease
    store.append(
        actor="orch",
        kind="lease.released",
        project_id="p1",
        task_id="t1",
        payload={"resource": "src/auth/**"},
    )
    events = store.read_all(project_id="p1")
    proj_after = DeterministicStateProjection.replay_from_events("p1", events)
    assert proj_after.leases.get_active_lease("src/auth/**") is None

    store.close()
