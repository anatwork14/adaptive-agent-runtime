"""Git worktree manager providing isolated task working trees."""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WorktreeError(RuntimeError):
    """Raised when git-backed isolation cannot be established safely."""


class WorktreeManager:
    """Manage isolated git worktrees for concurrent agent task execution.

    The manager is fail-closed: inability to create a real git worktree is a
    hard error. Silently falling back to a plain directory would violate the
    runtime's isolation and rollback guarantees.
    """

    def __init__(self, repo_path: str | Path, worktree_root: Optional[str | Path] = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        if worktree_root is None:
            self.worktree_root = self.repo_path / ".arc" / "worktrees"
        else:
            self.worktree_root = Path(worktree_root).resolve()
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def _run_git(
        self,
        args: list[str],
        cwd: Optional[Path] = None,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        target_cwd = cwd or self.repo_path
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(target_cwd),
                capture_output=True,
                text=True,
                check=check,
            )
        except FileNotFoundError as exc:
            raise WorktreeError("git executable is required for ARC isolation") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise WorktreeError(f"git {' '.join(args)} failed: {detail}") from exc

    def ensure_repository(self) -> None:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise WorktreeError(f"{self.repo_path} is not a git work tree")

    def ensure_integration_clean(self) -> None:
        """Require a clean integration tree before serialized integration."""
        self.ensure_repository()
        result = self._run_git(["status", "--porcelain"], check=False)
        ignored = []
        for line in result.stdout.splitlines():
            # ARC owns this directory and it must not make the repository look dirty.
            path = line[3:] if len(line) > 3 else line
            if path.startswith(".arc/") or path == ".arc":
                continue
            ignored.append(line)
        if ignored:
            raise WorktreeError(
                "integration worktree is dirty; refusing to merge candidate changes: "
                + "; ".join(ignored[:10])
            )

    def create_worktree(self, task_id: str, base_ref: str = "HEAD") -> Path:
        """Create an isolated task worktree and branch."""
        self.ensure_repository()
        branch_name = f"arc/task/{task_id}"
        worktree_path = self.worktree_root / task_id

        if worktree_path.exists():
            self.remove_worktree(task_id)

        branch_check = self._run_git(["rev-parse", "--verify", branch_name], check=False)
        if branch_check.returncode == 0:
            delete = self._run_git(["branch", "-D", branch_name], check=False)
            if delete.returncode != 0:
                raise WorktreeError(
                    f"cannot reset existing task branch {branch_name}: {delete.stderr.strip()}"
                )

        self._run_git(["worktree", "add", "-b", branch_name, str(worktree_path), base_ref])
        logger.info("Created worktree at %s on branch %s", worktree_path, branch_name)
        return worktree_path

    def commit_candidate(self, task_id: str, message: str) -> str:
        """Stage and commit an agent's changes, returning the immutable commit SHA.

        A real candidate commit is the unit consumed by the integration gate.
        No-op submissions are rejected because there is nothing meaningful to
        verify or merge.
        """
        worktree_path = self.worktree_root / task_id
        if not worktree_path.exists():
            raise WorktreeError(f"task worktree does not exist: {task_id}")

        self._run_git(["add", "-A"], cwd=worktree_path)
        staged = self._run_git(["diff", "--cached", "--quiet"], cwd=worktree_path, check=False)
        if staged.returncode == 0:
            raise WorktreeError(f"task {task_id} produced no repository changes")
        if staged.returncode not in (0, 1):
            raise WorktreeError(f"cannot inspect staged changes for task {task_id}")

        # Supply a repository-local identity if the host has no git identity.
        self._run_git(["-c", "user.name=ARC Agent", "-c", "user.email=arc@local", "commit", "-m", message], cwd=worktree_path)
        return self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()

    def get_commit_diff(self, commit_sha: str) -> str:
        """Return the exact patch represented by a candidate commit."""
        return self._run_git(["show", "--format=", "--binary", commit_sha]).stdout

    def branch_name(self, task_id: str) -> str:
        return f"arc/task/{task_id}"

    def remove_worktree(self, task_id: str) -> None:
        """Remove task worktree and its temporary branch."""
        branch_name = self.branch_name(task_id)
        worktree_path = self.worktree_root / task_id

        self._run_git(["worktree", "remove", "--force", str(worktree_path)], check=False)
        self._run_git(["branch", "-D", branch_name], check=False)

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        self._run_git(["worktree", "prune"], check=False)

    def get_diff(self, task_id: str, base_ref: str = "HEAD") -> str:
        """Get uncommitted diff in a task worktree.

        Kept for diagnostics. Production submissions should use
        :meth:`commit_candidate` and :meth:`get_commit_diff`.
        """
        worktree_path = self.worktree_root / task_id
        if not worktree_path.exists():
            return ""
        self._run_git(["add", "-A"], cwd=worktree_path, check=False)
        return self._run_git(["diff", "--cached", base_ref], cwd=worktree_path, check=False).stdout
