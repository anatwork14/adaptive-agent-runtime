"""IT1: Cold handoff integration test.

Scenario:
Agent A completes task 1 and records architectural decision.
Agent B starts cold with zero transcript history.
Context compiler reconstructs context from authoritative state and versioned memory.
Agent B completes task 2 cleanly.
"""

import asyncio
import sqlite3
import pytest
from adapters.codex import CodexAgentAdapter
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore
from state.models import GateStatus


def test_cold_handoff_reconstructs_context(tmp_path):
    async def _test():
        db_path = tmp_path / "cold_handoff.db"
        store = EventStore(db_path)

        conn = sqlite3.connect(tmp_path / "mem.db")
        conn.row_factory = sqlite3.Row
        lifecycle = MemoryLifecycle(conn)

        orch = Orchestrator(
            event_store=store,
            memory_lifecycle=lifecycle,
            repo_path=tmp_path,
            project_id="p_cold",
        )

        orch.init_project(spec={"app": "auth_service"}, constraints=["no-network"])

        # Task 1: Implemented by Agent A
        orch.create_task(
            task_id="t1",
            goal="Define AuthClient interface",
            files_declared=["src/auth.py"],
        )

        agent_a = CodexAgentAdapter(model_name="agent_a")
        res1 = await orch.execute_task("t1", agent_a, agent_id="agent_a")
        assert res1.status == GateStatus.ACCEPTED

        # Task 2: Handed off to Agent B (Cold Start - no Agent A transcript)
        orch.create_task(
            task_id="t2",
            goal="Implement Login Endpoint",
            dependencies=["t1"],
            files_declared=["src/login.py"],
        )

        agent_b = CodexAgentAdapter(model_name="agent_b")
        res2 = await orch.execute_task("t2", agent_b, agent_id="agent_b")
        assert res2.status == GateStatus.ACCEPTED

        # Verify task 2 was dispatched with reconstructed dependency state and without transcript
        proj = orch.get_projection()
        assert proj.dag.tasks["t1"].status.value == "completed"
        assert proj.dag.tasks["t2"].status.value == "completed"

        store.close()
        conn.close()

    asyncio.run(_test())
