"""Canonical V17 launcher: invoke the frozen runner with direct Python only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CAMPAIGN_DIR = Path(__file__).resolve().parent
ARC_ROOT = CAMPAIGN_DIR.parents[2]
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))

from launcher_identity import (  # noqa: E402
    assert_source_repository_clean,
    build_launcher_argv,
    inspect_python_executable,
)


def main() -> None:
    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))
    launcher = contract["launcher"]
    expected_script = Path(launcher["script_path"]).expanduser().resolve()
    if expected_script != Path(__file__).resolve():
        raise SystemExit(f"V17 launcher script identity mismatch: {expected_script}")
    identity = inspect_python_executable(
        sys.executable,
        expected_version=launcher["python_version"],
        expected_sha256=launcher["python_sha256"],
        expected_architecture=launcher["architecture"],
    )
    if identity.path != Path(launcher["python_path"]).expanduser().resolve():
        raise SystemExit(
            f"V17 Python launcher path mismatch: expected={launcher['python_path']}, actual={identity.path}"
        )
    assert_source_repository_clean(ARC_ROOT, stage="launcher_startup")

    from execute_campaign import main as execute_main  # noqa: PLC0415

    execute_main()


__all__ = ["build_launcher_argv", "main"]


if __name__ == "__main__":
    main()
