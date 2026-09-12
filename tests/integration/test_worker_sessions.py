"""Integration coverage for ARC v0.6 persistent worker sessions."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from application.session_app import SessionArcApplication
from application.sessions import SessionStatus
from cli.product import app as product_app
from state.models import GateStatus, TaskStatus
from tui.shell import ArcShell


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# session demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def test_worker_session_survives_application_restart_and_submits(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Create persistent worker artifact")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        assert session.status == SessionStatus.OPEN
        assert Path(session.worktree_path).exists()
        assert arc.get_task(task.task_id).status == TaskStatus.DISPATCHED  # type: ignore[union-attr]

        updated = asyncio.run(arc.sessions.send(session.session_id, "Implement the first draft"))
        assert updated.status == SessionStatus.OPEN
        assert any(message.role == "assistant" for message in updated.messages)
        changed = arc.sessions.changed_files(session.session_id)
        assert changed
        assert ".arc-mock" in arc.sessions.diff(session.session_id)
        session_id = session.session_id
        worktree = session.worktree_path

    # Session metadata, conversation, and draft worktree survive the ARC process.
    with SessionArcApplication(repo, "demo") as arc:
        restored = arc.sessions.get(session_id)
        assert restored is not None
        assert restored.status == SessionStatus.OPEN
        assert restored.worktree_path == worktree
        resumed = arc.sessions.resume(session_id)
        assert resumed.status == SessionStatus.OPEN
        assert Path(resumed.worktree_path).exists()

        result = asyncio.run(arc.sessions.submit(session_id))
        assert result.status == GateStatus.ACCEPTED
        final = arc.sessions.get(session_id)
        assert final is not None
        assert final.status == SessionStatus.ACCEPTED
        assert arc.get_task(task.task_id).status == TaskStatus.COMPLETED  # type: ignore[union-attr]
        assert not Path(worktree).exists()

    integrated = list(repo.glob(".arc-mock/*.txt"))
    assert integrated, "accepted persistent draft should be integrated into the repository"


def test_stopping_worker_discards_draft_and_returns_task_ready(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        task = arc.create_task("Draft something then stop")
        session = arc.sessions.create(task.task_id, agent_name="mock")
        asyncio.run(arc.sessions.send(session.session_id, "Make a draft"))
        worktree = Path(session.worktree_path)
        assert worktree.exists()

        stopped = arc.sessions.stop(session.session_id, reason="test cancellation")
        assert stopped.status == SessionStatus.STOPPED
        assert not worktree.exists()
        assert arc.get_task(task.task_id).status == TaskStatus.READY  # type: ignore[union-attr]
        kinds = [event.kind for event in arc.task_events(task.task_id)]
        assert "session.stopped" in kinds
        assert "recovery.retry" in kinds


def test_product_cli_exposes_session_attach_and_ui(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(product_app, ["init", str(repo), "--project-id", "demo"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(product_app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "session" in result.output
    assert "attach" in result.output
    assert "ui" in result.output

    result = runner.invoke(
        product_app,
        ["task", "create", "Interactive task", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        product_app,
        ["session", "open", "T001", "--agent", "mock", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output
    assert "ARC worker opened" in result.output

    result = runner.invoke(
        product_app,
        ["session", "list", "--repo", str(repo), "--project-id", "demo"],
    )
    assert result.exit_code == 0, result.output
    assert "T001" in result.output
    assert "mock" in result.output


@pytest.mark.asyncio
async def test_interactive_shell_mounts_and_accepts_slash_commands(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with SessionArcApplication(repo, "demo") as arc:
        arc.initialize()
        arc.create_task("Shell-visible task")

    shell = ArcShell(repo=repo, project_id="demo")
    async with shell.run_test(size=(120, 42)) as pilot:
        await pilot.pause()
        prompt = shell.query_one("#prompt")
        assert prompt is not None
        prompt.value = "/tasks"
        await pilot.press("enter")
        await pilot.pause()
        assert shell.query_one("#conversation") is not None
        assert shell.query_one("#sessionList") is not None
