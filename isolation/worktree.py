"""Git worktree manager providing isolated task working trees."""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manages isolated git worktrees for concurrent agent task execution."""

    def __init__(self, repo_path: str | Path, worktree_root: Optional[str | Path] = None) -> None:
        self.repo_path = Path(repo_path).resolve()
        if worktree_root is None:
            self.worktree_root = self.repo_path / ".arc" / "worktrees"
        else:
            self.worktree_root = Path(worktree_root).resolve()
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def _run_git(self, args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        target_cwd = cwd or self.repo_path
        return subprocess.run(
            ["git"] + args,
            cwd=str(target_cwd),
            capture_output=True,
            text=True,
            check=True,
        )

    def create_worktree(self, task_id: str, base_ref: str = "HEAD") -> Path:
        """Create an isolated worktree and branch for task_id."""
        branch_name = f"arc/task/{task_id}"
        worktree_path = self.worktree_root / task_id

        if worktree_path.exists():
            self.remove_worktree(task_id)

        try:
            # Check if branch exists
            check_branch = subprocess.run(
                ["git", "rev-parse", "--verify", branch_name],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
            )
            if check_branch.returncode == 0:
                # branch exists, delete it first to ensure clean state
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                )

            # Create worktree with new branch based on base_ref
            self._run_git(["worktree", "add", "-b", branch_name, str(worktree_path), base_ref])
            logger.info("Created worktree at %s on branch %s", worktree_path, branch_name)
            return worktree_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            # Fallback for environments without git or in mock mode
            worktree_path.mkdir(parents=True, exist_ok=True)
            logger.warning("Git worktree command failed (%s), using directory fallback %s", e, worktree_path)
            return worktree_path

    def remove_worktree(self, task_id: str) -> None:
        """Prune and remove worktree and branch for task_id."""
        branch_name = f"arc/task/{task_id}"
        worktree_path = self.worktree_root / task_id

        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def get_diff(self, task_id: str, base_ref: str = "HEAD") -> str:
        """Get git diff of changes in worktree against base_ref."""
        worktree_path = self.worktree_root / task_id
        if not worktree_path.exists():
            return ""

        try:
            # stage any uncommitted changes
            subprocess.run(["git", "add", "-A"], cwd=str(worktree_path), capture_output=True, text=True)
            res = subprocess.run(
                ["git", "diff", base_ref],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
            )
            return res.stdout
        except Exception as e:
            logger.warning("Failed to get diff from worktree: %s", e)
            return ""
