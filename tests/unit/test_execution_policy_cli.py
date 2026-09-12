"""CLI coverage for the ARC 0.9 environment-policy surface."""

from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from application.app import ArcApplication
from application.config import AgentProfile
from cli.product import app

runner = CliRunner()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# env policy\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def test_env_policy_sets_names_without_persisting_values(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    with ArcApplication(repo, "demo") as arc:
        arc.initialize()
        arc.add_agent(AgentProfile(name="builder", provider="codex"))

    monkeypatch.setenv("CUSTOM_PRIVATE_TOKEN", "secret-value-that-must-not-be-written")
    result = runner.invoke(
        app,
        [
            "env-policy",
            "builder",
            "--allow",
            "CUSTOM_PRIVATE_TOKEN",
            "--repo",
            str(repo),
            "--project-id",
            "demo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "CUSTOM_PRIVATE_TOKEN" in result.output
    assert "secret-value-that-must-not-be-written" not in result.output

    config_text = (repo / ".arc" / "config.yaml").read_text(encoding="utf-8")
    assert "CUSTOM_PRIVATE_TOKEN" in config_text
    assert "secret-value-that-must-not-be-written" not in config_text

    with ArcApplication(repo, "demo") as arc:
        assert arc.config.agents["builder"].env_allow == ["CUSTOM_PRIVATE_TOKEN"]


def test_env_policy_clear_removes_extra_names(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with ArcApplication(repo, "demo") as arc:
        arc.initialize()
        arc.add_agent(
            AgentProfile(name="builder", provider="codex", env_allow=["CUSTOM_TOOL_HOME"])
        )

    result = runner.invoke(
        app,
        [
            "env-policy",
            "builder",
            "--clear",
            "--repo",
            str(repo),
            "--project-id",
            "demo",
        ],
    )
    assert result.exit_code == 0, result.output
    with ArcApplication(repo, "demo") as arc:
        assert arc.config.agents["builder"].env_allow == []
