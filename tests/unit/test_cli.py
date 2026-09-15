"""Unit tests for the CLI commands."""

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_cli_init_status_and_events(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    # 1. arc init
    res_init = runner.invoke(app, ["init", str(repo_path), "--project-id", "cli_test"])
    assert res_init.exit_code == 0
    assert "ARC initialized" in res_init.stdout

    # 2. arc status
    res_status = runner.invoke(app, ["status", "--repo", str(repo_path), "--project-id", "cli_test"])
    assert res_status.exit_code == 0
    assert "cli_test" in res_status.stdout

    # 3. arc events
    res_events = runner.invoke(app, ["events", "--repo", str(repo_path), "--project-id", "cli_test"])
    assert res_events.exit_code == 0
    assert "project.created" in res_events.stdout

    # 4. arc replay
    res_replay = runner.invoke(app, ["replay", "--repo", str(repo_path), "--project-id", "cli_test"])
    assert res_replay.exit_code == 0
    assert "Replay successful" in res_replay.stdout
