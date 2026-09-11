"""End-to-End Pipeline test validating complete multi-agent workflow."""

import asyncio
import sqlite3
import pytest
from adapters.claude import ClaudeAgentAdapter
from adapters.codex import CodexAgentAdapter
from eval.faults.injector import FaultInjector
from eval.runners.experiment import ExperimentRunner
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from runtime.replay import ReplayEngine
from state.events import EventStore
from state.models import GateStatus


def test_full_multi_agent_pipeline_and_fault_recovery(tmp_path):
    async def _test():
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        db_path = repo_dir / "e2e_state.db"
        store = EventStore(db_path)

        mem_conn = sqlite3.connect(repo_dir / "e2e_mem.db")
        mem_conn.row_factory = sqlite3.Row
        lifecycle = MemoryLifecycle(mem_conn)

        orch = Orchestrator(
            event_store=store,
            memory_lifecycle=lifecycle,
            repo_path=repo_dir,
            project_id="p_e2e",
            verification_level="V0",
        )

        # 1. Project initialization
        orch.init_project(spec={"service": "payment_gateway"}, constraints=["no-direct-eval", "audit-logs"])

        # 2. Define task DAG
        orch.create_task("t_core", "Core Payment Models", files_declared=["src/models.py"])
        orch.create_task("t_api", "Payment API Endpoints", dependencies=["t_core"], files_declared=["src/api.py"])
        orch.create_task("t_audit", "Audit Logging Integration", dependencies=["t_api"], files_declared=["src/audit.py"])

        # 3. Schedule and execute t_core with Agent 1 (Codex)
        ready_tasks = orch.scheduler.get_ready_tasks()
        assert len(ready_tasks) == 1
        assert ready_tasks[0].task_id == "t_core"

        agent_codex = CodexAgentAdapter(model_name="gpt-4o")
        res_core = await orch.execute_task("t_core", agent_codex, agent_id="agent_codex")
        assert res_core.status == GateStatus.ACCEPTED

        # 4. Schedule and execute t_api with Agent 2 (Claude)
        ready_tasks = orch.scheduler.get_ready_tasks()
        assert any(t.task_id == "t_api" for t in ready_tasks)

        agent_claude = ClaudeAgentAdapter(model_name="claude-3-5-sonnet")
        res_api = await orch.execute_task("t_api", agent_claude, agent_id="agent_claude")
        assert res_api.status == GateStatus.ACCEPTED

        # 5. Fault Injection: Inject contradictory assumption before t_audit
        injector = FaultInjector(store, lifecycle)
        injector.inject_contradictory_assumption("p_e2e", topic="currency_conversion", created_event=store.current_version("p_e2e"))

        # Execute t_audit with Agent 1
        res_audit = await orch.execute_task("t_audit", agent_codex, agent_id="agent_codex")
        assert res_audit.status == GateStatus.ACCEPTED

        # 6. Verify Replay and Consistency (AC1, AC2)
        replay_engine = ReplayEngine(store)
        replayed = replay_engine.replay_project("p_e2e")
        assert replayed.version == store.current_version("p_e2e")
        assert len(replayed.project.state.completed_tasks) == 3

        # 7. Experiment Runner benchmark
        runner = ExperimentRunner()
        summary = await runner.run_benchmark(
            orchestrator=orch,
            task_ids=["t_core", "t_api"],
            agent=agent_codex,
        )
        assert summary.total_tasks == 2
        assert summary.resolved_rate == 1.0

        store.close()
        mem_conn.close()

    asyncio.run(_test())
