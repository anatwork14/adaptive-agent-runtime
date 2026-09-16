from __future__ import annotations

import sys
from pathlib import Path

V15_DIR = Path(__file__).parents[2] / "eval" / "campaigns" / "context-policy-multirepo-v15"
sys.path.insert(0, str(V15_DIR))

from launcher_identity import build_launcher_argv  # noqa: E402


def test_v15_launcher_uses_the_explicit_python_interpreter() -> None:
    python = Path("/qualified/.venv/bin/python")
    runner = Path("eval/campaigns/context-policy-multirepo-v15/execute_campaign.py")

    argv = build_launcher_argv(python, runner, ["--dry-run", "--attempt-id", "scratch"])

    assert argv == [
        "/qualified/.venv/bin/python",
        "eval/campaigns/context-policy-multirepo-v15/execute_campaign.py",
        "--dry-run",
        "--attempt-id",
        "scratch",
    ]
    assert "uv" not in argv
