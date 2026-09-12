"""Consume a private environment handoff and exec a tmux-owned runtime.

This helper exists so persistent tmux commands do not place secret environment
values in process arguments or tmux's recorded start command. Tmux receives only
the path to a mode-0600 JSON file. The helper reads and unlinks that file before
replacing itself with the actual worker process using the explicit environment.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_environment(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    finally:
        # Delete before the long-lived process starts. Failure to unlink should
        # not cause ARC to fall back to the ambient environment.
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if not isinstance(raw, dict):
        raise RuntimeError("ARC runtime environment handoff must be a JSON object")
    environment: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError("ARC runtime environment handoff must contain string pairs")
        environment[key] = value
    return environment


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[1] != "--":
        raise SystemExit("usage: python -m runtime.tmux_bootstrap ENV_FILE -- COMMAND [ARG ...]")
    env_path = Path(args[0])
    command = args[2:]
    if not command:
        raise SystemExit("ARC tmux bootstrap requires a command")
    environment = _load_environment(env_path)
    os.execvpe(command[0], command, environment)
    return 127  # pragma: no cover - exec replaces the process on success


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
