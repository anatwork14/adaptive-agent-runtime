from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from application.app import ArcApplication
from application.config import AgentProfile


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def test_orchestrator_routes_independent_tasks_in_same_batch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "parallel-demo") as arc:
        arc.initialize()
        arc.add_agent(
            AgentProfile(
                name="builder-a",
                provider="mock",
                role="implementation",
                capabilities=["implementation"],
                max_concurrency=2,
                quality_weight=1.2,
            )
        )
        arc.add_agent(
            AgentProfile(
                name="builder-b",
                provider="mock",
                role="implementation",
                capabilities=["implementation"],
                max_concurrency=2,
                quality_weight=1.1,
            )
        )
        first = arc.create_task(
            "implement alpha",
            task_type="implementation",
            required_capabilities=["implementation"],
            files=["src/alpha.py"],
        )
        second = arc.create_task(
            "implement beta",
            task_type="implementation",
            required_capabilities=["implementation"],
            files=["src/beta.py"],
        )

        result = asyncio.run(arc.orchestrate(max_parallel=2))

        assert set(result.accepted) == {first.task_id, second.task_id}
        assert (repo / "src" / "alpha.py").exists()
        assert (repo / "src" / "beta.py").exists()
        batches = [
            event
            for event in arc.recent_events(limit=200)
            if event.kind == "orchestration.batch_started"
        ]
        assert any(set(event.payload["tasks"]) == {first.task_id, second.task_id} for event in batches)


def test_overlapping_surfaces_are_deferred_then_run_on_fresh_head(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "overlap-demo") as arc:
        arc.initialize()
        first = arc.create_task(
            "first change",
            task_type="implementation",
            required_capabilities=["implementation"],
            files=["shared.py"],
        )
        second = arc.create_task(
            "second change",
            task_type="implementation",
            required_capabilities=["implementation"],
            files=["shared.py"],
        )
        result = asyncio.run(arc.orchestrate(max_parallel=2))

        assert set(result.accepted) == {first.task_id, second.task_id}
        assert second.task_id in result.deferred or first.task_id in result.deferred
        text = (repo / "shared.py").read_text(encoding="utf-8")
        assert first.task_id in text
        assert second.task_id in text


def test_plan_objective_materializes_dependency_dag_and_runs_until_idle(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "plan-demo") as arc:
        arc.initialize()
        plan, tasks = arc.plan_objective(
            "add authentication",
            files=["src/auth.py", "tests/test_auth.py"],
            acceptance=["tests pass"],
        )
        assert len(plan.tasks) == 2
        assert tasks[1].dependencies == [tasks[0].task_id]

        result = asyncio.run(arc.orchestrate(max_parallel=2))
        assert result.rounds == 2
        assert set(result.accepted) == {task.task_id for task in tasks}
        assert arc.get_task(tasks[0].task_id).status.value == "completed"
        assert arc.get_task(tasks[1].task_id).status.value == "completed"
        assert any(
            event.kind == "orchestration.plan_created"
            for event in arc.recent_events(limit=200)
        )
