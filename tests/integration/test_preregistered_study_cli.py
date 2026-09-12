import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cli.bootstrap import app


runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_preregister_run_plan_and_export_mock_study(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    base_commit = _git(repo, "rev-parse", "HEAD")

    manifest_paths: list[Path] = []
    for baseline in ("B3", "B5", "B7"):
        payload = {
            "benchmark_id": "cli-preregister-smoke",
            "baseline": baseline,
            "seed": 5,
            "agent_profile": "mock",
            "model": None,
            "repo_commit": base_commit,
            "context_token_budget": 2000,
            "hard_task_usd": 1.0,
            "tasks": [
                {
                    "task_id": "T001",
                    "goal": "Update app",
                    "files": ["app.py"],
                    "acceptance": ["repository change is produced"],
                    "risk": 0.1,
                    "token_budget": 2000,
                }
            ],
        }
        path = tmp_path / f"{baseline.lower()}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        manifest_paths.append(path)

    plan_path = tmp_path / "study-plan.json"
    preregister = runner.invoke(
        app,
        [
            "benchmark",
            "preregister",
            *(str(path) for path in manifest_paths),
            "--repo",
            str(repo),
            "--study-id",
            "cli-study",
            "--output",
            str(plan_path),
            "--repeats",
            "2",
            "--bootstrap-samples",
            "50",
            "--verification-level",
            "V1",
        ],
    )
    assert preregister.exit_code == 0, preregister.output
    assert plan_path.is_file()
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan_payload["runtime"]["verification_level"] == "V1"
    assert "verification_level=V1" in preregister.output

    results_root = tmp_path / "results"
    runtime_root = tmp_path / "runtime"
    execute = runner.invoke(
        app,
        [
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            str(repo),
            "--attempt-id",
            "a001",
            "--output-root",
            str(results_root),
            "--workspace-root",
            str(runtime_root),
        ],
    )
    assert execute.exit_code == 0, execute.output
    assert _git(repo, "rev-parse", "HEAD") == base_commit

    study_dir = results_root / "cli-preregister-smoke" / "studies" / "cli-study-a001"
    assert (study_dir / "study.json").is_file()
    provenance = json.loads((study_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["extra"]["preregistered"] is True
    assert provenance["extra"]["plan_digest"]

    export = runner.invoke(app, ["benchmark", "export", str(study_dir)])
    assert export.exit_code == 0, export.output
    export_root = study_dir / "exports"
    assert (export_root / "tasks.csv").is_file()
    assert (export_root / "repetitions.csv").is_file()
    assert (export_root / "pairs.csv").is_file()
    export_manifest = json.loads(
        (export_root / "export_manifest.json").read_text(encoding="utf-8")
    )
    assert export_manifest["plan_digest"] == provenance["extra"]["plan_digest"]
    assert export_manifest["row_counts"]["tasks"] == 6
