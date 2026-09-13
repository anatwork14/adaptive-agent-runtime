import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from cli import study_commands
from cli.bootstrap import app
from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.studies.preregistration import create_preregistration, save_preregistration

runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    command = ["git", *args]
    if args and args[0] == "commit":
        command[1:1] = ["-c", "commit.gpgsign=false"]
    proc = subprocess.run(
        command,
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
    export_manifest = json.loads((export_root / "export_manifest.json").read_text(encoding="utf-8"))
    assert export_manifest["plan_digest"] == provenance["extra"]["plan_digest"]
    assert export_manifest["row_counts"]["tasks"] == 6


def test_run_plan_passes_frozen_codex_identity_to_environment_validation(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    base_commit = _git(repo, "rev-parse", "HEAD")

    home = tmp_path / "codex-home"
    home.mkdir()
    config_path = home / "config.toml"
    config_path.write_text("trusted = true\n", encoding="utf-8")
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()
    (repo / ".arc").mkdir()
    (repo / ".arc" / "config.yaml").write_text(
        "project_id: test\n"
        "default_agent: builder\n"
        "hard_project_usd: 10.0\n"
        "provider_execution_timeout_seconds: 600\n"
        "visible_test_cmd: [python, -m, pytest, -q]\n"
        "visible_test_harness: {}\n"
        "agents:\n"
        "  builder:\n"
        "    name: builder\n"
        "    provider: codex\n"
        "    model: gpt-5.5\n"
        "    role: implementation\n"
        "    codex_home: "
        f"{home}\n"
        "    codex_config_path: "
        f"{config_path}\n",
        encoding="utf-8",
    )

    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text("assert True\n", encoding="utf-8")
    task = EvaluationTaskSpec(
        task_id="T001",
        goal="Update app",
        files=["app.py"],
        acceptance=["works"],
        token_budget=2000,
    )
    manifests = [
        BenchmarkManifest(
            benchmark_id="codex-identity-handoff",
            baseline=baseline,
            seed=5,
            agent_profile="builder",
            model="gpt-5.5",
            repo_commit=base_commit,
            context_token_budget=2000,
            hard_task_usd=1.0,
            tasks=[task],
        )
        for baseline in ("B3", "B5", "B7")
    ]
    plan = create_preregistration(
        manifests,
        repo,
        study_id="codex-identity-handoff",
        provider="codex",
        profile_role="implementation",
        profile_capabilities=["implementation"],
        visible_test_cmd=["python", "-m", "pytest", "-q"],
        visible_test_harness={
            "command": ["python", "-m", "pytest", "-q"],
            "backend": "docker",
            "image": "arc-v5-test:qualified",
            "image_digest": "sha256:" + "a" * 64,
            "python_toolchain": "CPython 3.11",
            "qualification_id": "codex-identity-handoff",
        },
        hard_project_usd=10.0,
        hidden_test_dir=hidden,
        verification_level="V1",
        provider_execution_timeout_seconds=600,
        provider_codex_home=str(home),
        provider_codex_config_path=str(config_path),
        provider_codex_config_sha256=config_sha,
        repeats=2,
        bootstrap_samples=2,
    )
    plan_path = save_preregistration(tmp_path / "plan.json", plan)

    monkeypatch.setattr(
        study_commands,
        "doctor_profile",
        lambda _profile: SimpleNamespace(status="READY"),
    )
    captured = {}

    def fake_validate(_plan, _repo, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(study_commands, "validate_execution_environment", fake_validate)
    monkeypatch.setattr(study_commands, "_print_result", lambda _result: None)
    runner_calls = []

    class FakeRunner:
        def __init__(self, *_args, **_kwargs):
            runner_calls.append(True)
            pass

        async def run(self, *_args, **_kwargs):
            return object()

    monkeypatch.setattr(study_commands, "RepeatedPairedBenchmarkRunner", FakeRunner)

    result = runner.invoke(
        app,
        [
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            str(repo),
            "--attempt-id",
            "a001",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["provider_codex_home"] == str(home)
    assert captured["provider_codex_config_path"] == str(config_path)
    assert captured["provider_codex_config_sha256"] == config_sha

    runner_calls.clear()
    qualification = runner.invoke(
        app,
        [
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            str(repo),
            "--attempt-id",
            "qualification",
            "--hidden-test-dir",
            str(hidden),
            "--qualification-only",
        ],
    )
    assert qualification.exit_code == 0, qualification.output
    assert runner_calls == []
    assert "run_plan_provider_environment_handoff=VERIFIED" in qualification.output
