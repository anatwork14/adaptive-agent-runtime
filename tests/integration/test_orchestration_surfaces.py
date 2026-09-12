from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from application.app import ArcApplication
from cli.entry import app as cli_app
from tui.dashboard import ArcDashboard
from webui.server import create_web_app


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


def test_cli_exposes_mission_route_and_orchestrate_commands() -> None:
    runner = CliRunner()
    root = runner.invoke(cli_app, ["--help"])
    assert root.exit_code == 0
    assert "orchestrate" in root.output
    assert "route" in root.output
    assert "mission" in root.output

    mission = runner.invoke(cli_app, ["mission", "--help"])
    assert mission.exit_code == 0
    assert "plan" in mission.output


def test_web_can_plan_route_and_orchestrate(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "web-orch") as arc:
        arc.initialize()

    client = TestClient(create_web_app(repo=repo, project_id="web-orch"))
    planned = client.post(
        "/api/missions/plan",
        json={
            "objective": "add auth",
            "files": ["src/auth.py", "tests/test_auth.py"],
            "acceptance": ["tests pass"],
        },
    )
    assert planned.status_code == 201, planned.text
    tasks = planned.json()["tasks"]
    assert len(tasks) == 2

    route = client.get(f"/api/tasks/{tasks[0]['task_id']}/route")
    assert route.status_code == 200, route.text
    assert route.json()["agent_name"] == "mock"

    result = client.post("/api/orchestration/run", json={"max_parallel": 2})
    assert result.status_code == 200, result.text
    assert result.json()["successful"] is True
    assert set(result.json()["accepted"]) == {task["task_id"] for task in tasks}
    assert (repo / "src" / "auth.py").exists()
    assert (repo / "tests" / "test_auth.py").exists()


def test_tui_mounts_with_fleet_binding(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    with ArcApplication(repo, "tui-orch") as arc:
        arc.initialize()
        arc.create_task(
            "write demo",
            task_type="implementation",
            required_capabilities=["implementation"],
            files=["demo.py"],
        )

    async def exercise() -> None:
        app = ArcDashboard(repo=repo, project_id="tui-orch")
        async with app.run_test() as pilot:
            assert any(binding.key == "a" for binding in app.BINDINGS)
            await pilot.press("a")
            await pilot.pause(0.5)

    import asyncio

    asyncio.run(exercise())
    assert (repo / "demo.py").exists()
