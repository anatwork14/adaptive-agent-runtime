from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
LAUNCHER = REPO_ROOT / "eval" / "campaigns" / "context-policy-multirepo-v15" / "launch_v15.py"


def _git_status() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_direct_v15_launcher_does_not_add_source_repository_artifacts() -> None:
    before = _git_status()
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "uv run" not in result.stdout
    assert _git_status() == before
    assert not (REPO_ROOT / "uv.lock").exists()
