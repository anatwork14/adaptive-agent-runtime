"""IT1: Cold handoff integration test.

Scenario:
Agent A completes task 1.
Agent B starts cold with zero transcript history.
ARC reconstructs dependency/project context from authoritative state and memory.
Both candidates must be committed, gated, and integrated into a real git repo.
"""

import asyncio
import sqlite3
import subprocess

from adapters.mock import MockAgentAdapter
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
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


def test_cold_handoff_reconstructs_context(tmp_path):
    async def _test():
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# auth service\n", encoding="utf-8")
        _git(repo, "init", "-b", "main")
        _git(repo, "add", "README.md")
        _git(
            repo,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@local",
            "commit",
            "-m",
            "base",
        )

        # Runtime state stays outside the repository so the serialized
        # integration tree remains clean.
        store = EventStore(tmp_path / "cold_handoff.db")
        conn = sqlite3.connect(tmp_path / "mem.db")
        conn.row_factory = sqlite3.Row
        lifecycle = MemoryLifecycle(conn)

        orchestrator = Orchestrator(
            event_store=store,
            memory_lifecycle=lifecycle,
            repo_path=repo,
            project_id="p_cold",
        )
        orchestrator.init_project(
            spec={"app": "auth_service"},
            constraints=["no-network"],
        )

        orchestrator.create_task(
            task_id="t1",
            goal="Define AuthClient interface",
            files_declared=["src/auth.py"],
        )
        agent_a = MockAgentAdapter(name="agent-a-test-double")
        result1 = await orchestrator.execute_task("t1", agent_a, agent_id="agent_a")
        assert result1.status == GateStatus.ACCEPTED
        assert (repo / "src/auth.py").exists()

        # Agent B receives no Agent A transcript. Its new packet is compiled from
        # current project state after t1 has been integrated.
        orchestrator.create_task(
            task_id="t2",
            goal="Implement Login Endpoint",
            dependencies=["t1"],
            files_declared=["src/login.py"],
        )
        agent_b = MockAgentAdapter(name="agent-b-test-double")
        result2 = await orchestrator.execute_task("t2", agent_b, agent_id="agent_b")
        assert result2.status == GateStatus.ACCEPTED
        assert (repo / "src/login.py").exists()

        projection = orchestrator.get_projection()
        assert projection.dag.tasks["t1"].status.value == "completed"
        assert projection.dag.tasks["t2"].status.value == "completed"

        # Context events demonstrate a fresh, versioned handoff rather than raw
        # transcript reuse.
        context_events = [
            event
            for event in store.read_all(project_id="p_cold")
            if event.kind == "context.compiled"
        ]
        assert len(context_events) == 2
        assert context_events[1].payload["state_version"] > context_events[0].payload["state_version"]

        store.close()
        conn.close()

    asyncio.run(_test())
