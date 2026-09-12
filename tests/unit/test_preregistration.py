import json
import subprocess

import pytest

from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.studies.preregistration import (
    ExecutionHarness,
    create_preregistration,
    load_preregistration,
    save_preregistration,
    validate_execution_environment,
)

HARNESS = {
    "command": ["python", "-m", "pytest", "-q"],
    "backend": "docker",
    "image": "arc-v2-test:qualified",
    "image_digest": "sha256:" + "a" * 64,
    "environment": {"PYTHONPATH": "/workspace"},
    "hidden_command": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
    "hidden_environment": {"PYTHONPATH": "/workspace"},
    "python_toolchain": "CPython 3.11.16",
    "timeout_seconds": 60,
    "qualification_id": "synthetic-v2-harness",
}


def _git(repo, *args):
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


def _manifests(commit: str) -> list[BenchmarkManifest]:
    task = EvaluationTaskSpec(
        task_id="T001",
        goal="Update app",
        files=["app.py"],
        acceptance=["works"],
        token_budget=4000,
    )
    common = dict(
        benchmark_id="provider-study",
        seed=17,
        agent_profile="builder",
        model="mock-model",
        repo_commit=commit,
        context_token_budget=4000,
        hard_task_usd=1.0,
        tasks=[task],
    )
    return [BenchmarkManifest(baseline=baseline, **common) for baseline in ("B3", "B5", "B7")]


def test_preregistration_digest_and_environment_fail_closed(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    commit = _git(repo, "rev-parse", "HEAD")

    hidden = tmp_path / "hidden"
    hidden.mkdir()
    (hidden / "test_hidden.py").write_text("assert True\n", encoding="utf-8")

    plan = create_preregistration(
        _manifests(commit),
        repo,
        study_id="study-provider-001",
        provider="mock",
        profile_role="builder",
        profile_capabilities=["implementation", "test"],
        visible_test_cmd=["python", "-m", "pytest", "-q"],
        visible_test_harness=HARNESS,
        hard_project_usd=10.0,
        hidden_test_dir=hidden,
        repeats=6,
        bootstrap_samples=500,
        ci=0.95,
        exclusions=["provider outage before first task"],
        created_at_utc="2026-09-12T00:00:00+00:00",
    )
    path = save_preregistration(tmp_path / "plan.json", plan)
    loaded = load_preregistration(path)
    assert loaded.plan_digest == plan.plan_digest
    assert loaded.canonical_repo_commit == commit
    assert loaded.planned_comparisons == ["B3-B5", "B3-B7", "B5-B7"]

    validate_execution_environment(
        loaded,
        repo,
        provider="mock",
        model="mock-model",
        profile_role="builder",
        profile_capabilities=["test", "implementation"],
        visible_test_cmd=["python", "-m", "pytest", "-q"],
        visible_test_harness=HARNESS,
        hard_project_usd=10.0,
        hidden_test_dir=hidden,
    )

    (hidden / "test_hidden.py").write_text("assert False\n", encoding="utf-8")
    with pytest.raises(ValueError, match="execution environment differs"):
        validate_execution_environment(
            loaded,
            repo,
            provider="mock",
            model="mock-model",
            profile_role="builder",
            profile_capabilities=["implementation", "test"],
            visible_test_cmd=["python", "-m", "pytest", "-q"],
            visible_test_harness=HARNESS,
            hard_project_usd=10.0,
            hidden_test_dir=hidden,
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["design"]["repeats"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_preregistration(path)


def test_harness_is_part_of_plan_digest_and_environment_contract(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "arc@example.test")
    _git(repo, "config", "user.name", "ARC Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "base")
    commit = _git(repo, "rev-parse", "HEAD")
    plan = create_preregistration(
        _manifests(commit),
        repo,
        study_id="study-harness",
        provider="mock",
        profile_role="builder",
        profile_capabilities=["implementation"],
        visible_test_cmd=HARNESS["command"],
        visible_test_harness=HARNESS,
        hard_project_usd=10.0,
    )
    path = save_preregistration(tmp_path / "harness-plan.json", plan)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["runtime"]["visible_test_harness"]["image_digest"] = "sha256:" + "b" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_preregistration(path)

    validate_execution_environment(
        plan,
        repo,
        provider="mock",
        model="mock-model",
        profile_role="builder",
        profile_capabilities=["implementation"],
        visible_test_cmd=HARNESS["command"],
        visible_test_harness=ExecutionHarness.model_validate(HARNESS),
        hard_project_usd=10.0,
        hidden_test_dir=None,
    )

    drifted_harness = dict(HARNESS)
    drifted_harness["timeout_seconds"] = HARNESS["timeout_seconds"] + 1
    with pytest.raises(ValueError, match="execution environment differs"):
        validate_execution_environment(
            plan,
            repo,
            provider="mock",
            model="mock-model",
            profile_role="builder",
            profile_capabilities=["implementation"],
            visible_test_cmd=HARNESS["command"],
            visible_test_harness=drifted_harness,
            hard_project_usd=10.0,
            hidden_test_dir=None,
        )
