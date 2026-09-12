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

    Linked worktrees live outside the integration repository by default. This
    avoids recursive-worktree/status edge cases and keeps the integration tree
    clean without relying on ignore rules.
    """

    def __init__(self, repo_path: str | Path, worktree_root: Optional[str | Path] = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        if worktree_root is None:
            self.worktree_root = (
                self.repo_path.parent
                / ".arc-runtime"
                / self.repo_path.name
                / "worktrees"
            )
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
        self.ensure_repository()
        result = self._run_git(["status", "--porcelain"], check=False)
        if result.stdout.strip():
            raise WorktreeError(
                "integration worktree is dirty; refusing to merge candidate changes: "
                + "; ".join(result.stdout.splitlines()[:10])
            )

    def create_worktree(self, task_id: str, base_ref: str = "HEAD") -> Path:
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
        """Freeze the worker's exact candidate commit.

        Normal workers leave an uncommitted draft, which ARC stages and commits.
        Interactive/review workers may already have committed their draft (for
        example before pushing a PR). In that case ARC accepts the current HEAD
        only when it contains commits that are not reachable from the current
        integration HEAD. A clean branch with no worker-authored commit still
        fails closed as a no-op.
        """
        worktree_path = self.worktree_root / task_id
        if not worktree_path.exists():
            raise WorktreeError(f"task worktree does not exist: {task_id}")

        self._run_git(["add", "-A"], cwd=worktree_path)
        staged = self._run_git(["diff", "--cached", "--quiet"], cwd=worktree_path, check=False)
        if staged.returncode == 0:
            integration_head = self._run_git(["rev-parse", "HEAD"]).stdout.strip()
            ahead = self._run_git(
                ["rev-list", "--count", "HEAD", "--not", integration_head],
                cwd=worktree_path,
                check=False,
            )
            if ahead.returncode == 0 and int((ahead.stdout or "0").strip() or "0") > 0:
                return self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()
            raise WorktreeError(f"task {task_id} produced no repository changes")
        if staged.returncode not in (0, 1):
            raise WorktreeError(f"cannot inspect staged changes for task {task_id}")

        self._run_git(
            [
                "-c",
                "user.name=ARC Agent",
                "-c",
                "user.email=arc@local",
                "commit",
                "-m",
                message,
            ],
            cwd=worktree_path,
        )
        return self._run_git(["rev-parse", "HEAD"], cwd=worktree_path).stdout.strip()

    def get_commit_diff(self, commit_sha: str) -> str:
        return self._run_git(["show", "--format=", "--binary", commit_sha]).stdout

    def branch_name(self, task_id: str) -> str:
        return f"arc/task/{task_id}"

    def remove_worktree(self, task_id: str) -> None:
        branch_name = self.branch_name(task_id)
        worktree_path = self.worktree_root / task_id

        self._run_git(["worktree", "remove", "--force", str(worktree_path)], check=False)
        self._run_git(["branch", "-D", branch_name], check=False)
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        self._run_git(["worktree", "prune"], check=False)

    def get_diff(self, task_id: str, base_ref: str = "HEAD") -> str:
        worktree_path = self.worktree_root / task_id
        if not worktree_path.exists():
            return ""
        self._run_git(["add", "-A"], cwd=worktree_path, check=False)
        return self._run_git(["diff", "--cached", base_ref], cwd=worktree_path, check=False).stdout
