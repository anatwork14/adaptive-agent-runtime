"""Integration coverage for the shared application layer, CLI v2, and TUI."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from application.app import ArcApplication
from application.config import AgentProfile
from cli.main import app as cli_app
from state.models import GateStatus, TaskStatus
from tui.dashboard import ArcDashboard


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


def test_application_task_and_agent_lifecycle(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task(
            "Create an ARC demo artifact",
            files=["arc_demo.txt"],
            acceptance=["candidate integrates through the gate"],
            risk=0.2,
        )
        assert task.task_id == "T001"
        assert task.status == TaskStatus.READY

        arc.add_agent(AgentProfile(name="builder", provider="mock", role="implementation"))
        assert {profile.name for profile in arc.list_agents()} == {"builder", "mock"}
        doctor = {row.name: row for row in arc.doctor_agents()}
        assert doctor["builder"].status == "READY"

        result = asyncio.run(arc.run_task(task.task_id, agent_name="builder"))
        assert result.status == GateStatus.ACCEPTED
        assert (repo / "arc_demo.txt").exists()
        assert arc.get_task(task.task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]
        assert any(event.kind == "gate.accepted" for event in arc.task_events(task.task_id))


def test_retry_and_cancel_are_authoritative_events(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "demo") as arc:
        arc.initialize()
        failed = arc.create_task("A task that will fail", task_id="T010")
        arc.event_store.append(
            actor="test",
            kind="task.failed",
            project_id="demo",
            task_id=failed.task_id,
            payload={"reason": "synthetic failure"},
        )
        assert arc.get_task("T010").status == TaskStatus.FAILED  # type: ignore[union-attr]
        retried = arc.retry_task("T010")
        assert retried.status == TaskStatus.READY
        cancelled = arc.cancel_task("T010")
        assert cancelled.status == TaskStatus.ABANDONED
        kinds = [event.kind for event in arc.task_events("T010")]
        assert "recovery.retry" in kinds
        assert "task.abandoned" in kinds


def test_cli_v2_create_list_and_agent_profile(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_app, ["init", str(repo), "--project-id", "demo"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        cli_app,
        [
            "task",
            "create",
            "Implement a demo task",
            "--file",
            "demo.py",
            "--repo",
            str(repo),
            "--project-id",
            "demo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "T001" in result.output

    result = runner.invoke(
        cli_app,
        ["agent", "add", "builder", "--provider", "mock", "--default", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        cli_app,
        ["task", "list", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output
    assert "Implement a demo task" in result.output

    result = runner.invoke(
        cli_app,
        ["agent", "doctor", "builder", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output
    assert "READY" in result.output


@pytest.mark.asyncio
async def test_dashboard_mounts_against_real_application_state(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "demo") as arc:
        arc.initialize()
        arc.create_task("Visible in dashboard", task_id="T001")

    dashboard = ArcDashboard(repo=repo, project_id="demo")
    async with dashboard.run_test(size=(120, 42)) as pilot:
        await pilot.pause()
        table = dashboard.query_one("#task-table")
        assert getattr(table, "row_count", 0) == 1
        assert dashboard.query_one("#system") is not None
        assert dashboard.query_one("#events") is not None
