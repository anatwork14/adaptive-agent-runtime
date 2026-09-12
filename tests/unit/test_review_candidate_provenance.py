"""Regression coverage for public review SHA vs synthetic gate candidate identity."""

from __future__ import annotations

import subprocess
from pathlib import Path

from isolation.worktree import WorktreeManager


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    return repo


def _rev(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_multi_commit_worker_freezes_without_rewriting_public_branch(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    base_sha = _rev(repo, "rev-parse", "HEAD")
    manager = WorktreeManager(repo)
    worktree = manager.create_worktree("T001")

    (worktree / "one.txt").write_text("one\n", encoding="utf-8")
    first = manager.commit_candidate("T001", "first")
    assert first == _rev(worktree, "rev-parse", "HEAD")

    (worktree / "two.txt").write_text("two\n", encoding="utf-8")
    synthetic = manager.commit_candidate("T001", "second")
    public_head = _rev(worktree, "rev-parse", "HEAD")

    assert synthetic != public_head
    assert manager.branch_name("T001") == "arc/task/T001"
    branch_ref = _rev(repo, "rev-parse", manager.branch_name("T001"))
    assert branch_ref == public_head

    # The synthetic candidate contains the complete branch delta, not only the
    # final commit's diff, while the public branch remains two commits ahead.
    diff = manager.get_commit_diff(synthetic)
    assert "one.txt" in diff
    assert "two.txt" in diff
    assert _rev(worktree, "rev-list", "--count", "HEAD", "--not", base_sha) == "2"
