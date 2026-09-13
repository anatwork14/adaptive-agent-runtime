"""Regression coverage for ARC Git operations under hostile host configuration."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from adapters.base import AgentRunResult
from adapters.mock import MockAgentAdapter
from isolation.worktree import WorktreeManager
from memory.lifecycle import MemoryLifecycle
from runtime.gate import IntegrationGate
from runtime.git import arc_git_write_args
from runtime.orchestrator import Orchestrator
from state.events import EventStore
from state.models import GateStatus, PatchSubmission


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(
        repo,
        *arc_git_write_args(
            ["commit", "-m", "base"],
            user_name="ARC Fixture",
            user_email="arc-fixture@local",
        ),
    )
    return repo


def _hostile_git_environment(monkeypatch: pytest.MonkeyPatch, key_path: Path) -> dict[str, str]:
    hostile = os.environ.copy()
    config = {
        "commit.gpgsign": "true",
        "gpg.format": "ssh",
        "user.signingkey": str(key_path),
        "user.name": "Hostile Host",
        "user.email": "hostile@local",
    }
    hostile["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config.items()):
        hostile[f"GIT_CONFIG_KEY_{index}"] = key
        hostile[f"GIT_CONFIG_VALUE_{index}"] = value
    hostile["GIT_TERMINAL_PROMPT"] = "0"
    for key, value in hostile.items():
        monkeypatch.setenv(key, value)
    return hostile


def _commit_identity(repo: Path, commit_sha: str) -> list[str]:
    return _git(repo, "show", "-s", "--format=%an%n%ae%n%cn%n%ce", commit_sha).splitlines()


def _global_git_config_snapshot() -> str:
    """Read global config without allowing test-only injected config entries."""
    clean = os.environ.copy()
    for key in list(clean):
        if key == "GIT_CONFIG_COUNT" or key.startswith("GIT_CONFIG_KEY_") or key.startswith(
            "GIT_CONFIG_VALUE_"
        ):
            clean.pop(key, None)
    result = subprocess.run(
        ["git", "config", "--global", "--null", "--list"],
        env=clean,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def test_v2_signing_failure_reproduced_and_arc_pipeline_is_hermetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _create_repo(tmp_path)
    global_config_before = _global_git_config_snapshot()
    hostile = _hostile_git_environment(monkeypatch, tmp_path / "missing-signing-key")

    # Reproduce the V2 defect with the legacy candidate-commit operation. The
    # missing key makes signing fail deterministically without an interactive
    # passphrase prompt.
    (repo / "legacy.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "legacy.py", env=hostile)
    legacy = subprocess.run(
        ["git", "commit", "-m", "legacy candidate"],
        cwd=repo,
        env=hostile,
        capture_output=True,
        text=True,
        check=False,
    )
    assert legacy.returncode != 0
    assert "sign" in (legacy.stdout + legacy.stderr).lower()
    _git(repo, "reset", "--", "legacy.py", env=hostile)
    (repo / "legacy.py").unlink()

    manager = WorktreeManager(repo, tmp_path / "worktrees")
    workspace = manager.create_worktree("T001")
    try:
        (workspace / "candidate.py").write_text("def candidate():\n    return 1\n", encoding="utf-8")
        candidate_sha = manager.commit_candidate("T001", "arc(T001): candidate")
        assert _commit_identity(repo, candidate_sha) == [
            "ARC Agent",
            "arc@local",
            "ARC Agent",
            "arc@local",
        ]

        store = EventStore(tmp_path / "events.db")
        try:
            gate = IntegrationGate(store, "project", repo, verification_level="V0")
            submission = PatchSubmission(
                patch_id="patch_T001",
                task_id="T001",
                agent_id="builder",
                context_id="ctx_T001",
                dispatch_state_version=1,
                candidate_commit_sha=candidate_sha,
                candidate_branch="arc/task/T001",
                diff=manager.get_commit_diff(candidate_sha),
                summary="candidate completed",
            )
            result = gate.evaluate_submission(submission)
            assert result.status == GateStatus.ACCEPTED
            assert (repo / "candidate.py").exists()
            assert _commit_identity(repo, result.merged_commit_sha or "") == [
                "ARC Agent",
                "arc@local",
                "ARC Gate",
                "arc-gate@local",
            ]
            event_kinds = [event.kind for event in store.read_all(project_id="project")]
            assert "gate.started" in event_kinds
            assert "gate.accepted" in event_kinds
        finally:
            store.close()
        assert _global_git_config_snapshot() == global_config_before
    finally:
        manager.remove_worktree("T001")


def test_multi_commit_squash_uses_deterministic_identity_under_hostile_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _create_repo(tmp_path)
    hostile = _hostile_git_environment(monkeypatch, tmp_path / "missing-signing-key")
    manager = WorktreeManager(repo, tmp_path / "worktrees")
    workspace = manager.create_worktree("T002")
    try:
        (workspace / "first.py").write_text("first = True\n", encoding="utf-8")
        _git(workspace, "add", "first.py", env=hostile)
        _git(
            workspace,
            *arc_git_write_args(
                ["commit", "-m", "first candidate commit"],
                user_name="ARC Worker",
                user_email="arc-worker@local",
            ),
            env=hostile,
        )
        (workspace / "second.py").write_text("second = True\n", encoding="utf-8")
        _git(workspace, "add", "second.py", env=hostile)
        _git(
            workspace,
            *arc_git_write_args(
                ["commit", "-m", "second candidate commit"],
                user_name="ARC Worker",
                user_email="arc-worker@local",
            ),
            env=hostile,
        )

        candidate_sha = manager.commit_candidate("T002", "arc(T002): squash candidate")
        assert _commit_identity(repo, candidate_sha) == [
            "ARC Agent",
            "arc@local",
            "ARC Agent",
            "arc@local",
        ]
        assert "first.py" in manager.get_commit_diff(candidate_sha)
        assert "second.py" in manager.get_commit_diff(candidate_sha)
    finally:
        manager.remove_worktree("T002")


def test_orchestrator_submission_and_gate_complete_under_hostile_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _create_repo(tmp_path)
    _hostile_git_environment(monkeypatch, tmp_path / "missing-signing-key")
    event_store = EventStore(tmp_path / "events.db")
    memory_connection = sqlite3.connect(tmp_path / "memory.db", check_same_thread=False)
    try:
        orchestrator = Orchestrator(
            event_store,
            MemoryLifecycle(memory_connection),
            repo,
            "project",
            verification_level="V0",
            hard_task_usd=2.0,
            hard_project_usd=10.0,
        )
        orchestrator.init_project(spec={"name": "hostile-git"})
        orchestrator.create_task(
            task_id="T003",
            goal="write a candidate file",
            files_declared=["candidate.py"],
            acceptance_criteria=["candidate integrates"],
            token_budget=1000,
        )

        def handler(context, workspace: Path) -> AgentRunResult:
            (workspace / "candidate.py").write_text("value = 3\n", encoding="utf-8")
            return AgentRunResult(
                status="completed",
                summary="fake provider completed",
                token_usage={"prompt_tokens": 1, "completion_tokens": 1},
            )

        result = asyncio.run(
            orchestrator.execute_task(
                "T003",
                MockAgentAdapter(name="fake-provider", handler=handler),
                "builder",
            )
        )
        assert result.status == GateStatus.ACCEPTED
        events = event_store.read_all(project_id="project")
        event_kinds = [event.kind for event in events]
        assert event_kinds.index("task.submitted") < event_kinds.index("gate.started")
        assert "gate.accepted" in event_kinds
        candidate_event = next(event for event in events if event.kind == "task.submitted")
        candidate_sha = candidate_event.payload["candidate_commit_sha"]
        assert _commit_identity(repo, candidate_sha) == [
            "ARC Agent",
            "arc@local",
            "ARC Agent",
            "arc@local",
        ]
        assert (repo / "candidate.py").read_text(encoding="utf-8") == "value = 3\n"
        assert not _git(repo, "status", "--porcelain", env=os.environ.copy())
    finally:
        memory_connection.close()
        event_store.close()
