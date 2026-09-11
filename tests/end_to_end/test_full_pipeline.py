"""End-to-end test for the real git-backed ARC control flow."""

import asyncio
import sqlite3
import subprocess

from adapters.mock import MockAgentAdapter
from eval.faults.injector import FaultInjector
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from runtime.replay import ReplayEngine
from state.events import EventStore
from state.models import GateStatus


def _git(repo, *args):
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_full_multi_agent_pipeline_and_fault_recovery(tmp_path):
    async def _test():
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "README.md").write_text("# test repo\n", encoding="utf-8")
        _git(repo_dir, "init", "-b", "main")
        _git(repo_dir, "add", "README.md")
        _git(
            repo_dir,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@local",
            "commit",
            "-m",
            "base",
        )

        # Keep authoritative/derived databases outside the repository so the
        # single-writer integration tree remains clean by construction.
        store = EventStore(tmp_path / "e2e_state.db")
        mem_conn = sqlite3.connect(tmp_path / "e2e_mem.db")
        mem_conn.row_factory = sqlite3.Row
        lifecycle = MemoryLifecycle(mem_conn)

        orchestrator = Orchestrator(
            event_store=store,
            memory_lifecycle=lifecycle,
            repo_path=repo_dir,
            project_id="p_e2e",
            verification_level="V0",
        )

        orchestrator.init_project(
            spec={"service": "payment_gateway"},
            constraints=["no-direct-eval", "audit-logs"],
        )
        orchestrator.create_task(
            "t_core",
            "Core Payment Models",
            files_declared=["src/models.py"],
        )
        orchestrator.create_task(
            "t_api",
            "Payment API Endpoints",
            dependencies=["t_core"],
            files_declared=["src/api.py"],
        )
        orchestrator.create_task(
            "t_audit",
            "Audit Logging Integration",
            dependencies=["t_api"],
            files_declared=["src/audit.py"],
        )

        codex_mock = MockAgentAdapter(name="codex-test-double")
        claude_mock = MockAgentAdapter(name="claude-test-double")

        result_core = await orchestrator.execute_task(
            "t_core", codex_mock, agent_id="agent_codex"
        )
        assert result_core.status == GateStatus.ACCEPTED
        assert (repo_dir / "src/models.py").exists()

        result_api = await orchestrator.execute_task(
            "t_api", claude_mock, agent_id="agent_claude"
        )
        assert result_api.status == GateStatus.ACCEPTED
        assert (repo_dir / "src/api.py").exists()

        injector = FaultInjector(store, lifecycle)
        injector.inject_contradictory_assumption(
            "p_e2e",
            topic="currency_conversion",
            created_event=store.current_version("p_e2e"),
        )

        result_audit = await orchestrator.execute_task(
            "t_audit", codex_mock, agent_id="agent_codex"
        )
        assert result_audit.status == GateStatus.ACCEPTED
        assert (repo_dir / "src/audit.py").exists()

        # Authoritative state replay must reproduce task completion.
        replayed = ReplayEngine(store).replay_project("p_e2e")
        assert replayed.version == store.current_version("p_e2e")
        assert len(replayed.project.state.completed_tasks) == 3

        # Derived memory must be reconstructable from recorded materialization
        # events without re-running candidate extraction or a model.
        before_ids = {
            memory.memory_id
            for memory in lifecycle.get_active_memories("p_e2e")
        }
        restored_ids = set(
            lifecycle.rebuild_from_events(
                store.read_all(project_id="p_e2e"),
                project_id="p_e2e",
            )
        )
        assert before_ids.issubset(restored_ids)

        # Candidate changes actually landed on integration/main.
        assert _git(repo_dir, "status", "--porcelain") in ("", "?? .arc/")
        assert len(_git(repo_dir, "log", "--oneline").splitlines()) >= 4

        store.close()
        mem_conn.close()

    asyncio.run(_test())
