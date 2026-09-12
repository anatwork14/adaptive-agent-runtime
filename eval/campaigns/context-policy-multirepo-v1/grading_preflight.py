"""Campaign-specific grading-environment health checks.

The provider study must not begin unless the untouched pinned repository passes
its own visible suite in the exact sandbox that will grade candidates. The
import probe also proves src-layout projects resolve candidate code from the
mounted worktree instead of an unrelated site-packages installation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from isolation.container import SandboxRunner, WORKSPACE_PYTHONPATH


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git command failed").strip()
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return proc


def _test_env() -> dict[str, str]:
    return {
        "PYTHONPATH": WORKSPACE_PYTHONPATH,
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def validate_base_grading_environment(
    repo: str | Path,
    *,
    commit: str,
    visible_test_cmd: Sequence[str],
    import_module: str,
    expected_import_prefix: str,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    """Test a detached untouched base in the configured grading sandbox."""
    source = Path(repo).resolve()
    temp_root = Path(tempfile.mkdtemp(prefix="arc-grading-preflight-"))
    worktree = temp_root / "worktree"
    added = False
    try:
        _git(source, "worktree", "add", "--detach", str(worktree), commit)
        added = True
        sandbox = SandboxRunner(worktree, timeout_seconds=timeout_seconds)
        probe_code = (
            "import importlib, pathlib; "
            f"m=importlib.import_module({import_module!r}); "
            "print(pathlib.Path(m.__file__).resolve())"
        )
        probe = sandbox.run_command(
            ["python", "-c", probe_code],
            env_vars=_test_env(),
            timeout=60,
        )
        if probe.exit_code != 0:
            output = (probe.stdout + "\n" + probe.stderr)[-4000:]
            raise RuntimeError(
                f"candidate import probe failed for {import_module!r}:\n{output}"
            )
        import_lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
        if not import_lines:
            raise RuntimeError(f"candidate import probe returned no path for {import_module!r}")
        imported_from = import_lines[-1]
        if not imported_from.startswith(expected_import_prefix):
            raise RuntimeError(
                f"candidate import escaped mounted source for {import_module!r}: "
                f"expected prefix={expected_import_prefix!r}, actual={imported_from!r}"
            )

        command = list(visible_test_cmd)
        if not command:
            raise RuntimeError("visible test command is empty")
        tests = sandbox.run_command(
            command,
            env_vars=_test_env(),
            timeout=timeout_seconds,
        )
        if tests.exit_code != 0:
            output = (tests.stdout + "\n" + tests.stderr)[-8000:]
            raise RuntimeError(
                "untouched pinned repository does not pass the frozen visible-test "
                f"environment (exit={tests.exit_code}, timed_out={tests.timed_out}):\n{output}"
            )

        test_output = tests.stdout + "\n" + tests.stderr
        return {
            "repo_commit": commit,
            "import_module": import_module,
            "imported_from": imported_from,
            "pythonpath": WORKSPACE_PYTHONPATH,
            "visible_test_cmd": command,
            "visible_tests_passed": True,
            "visible_test_duration_ms": tests.duration_ms,
            "visible_test_output_sha256": hashlib.sha256(
                test_output.encode("utf-8")
            ).hexdigest(),
        }
    finally:
        if added:
            _git(source, "worktree", "remove", "--force", str(worktree), check=False)
            _git(source, "worktree", "prune", check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    """No standalone CLI; freeze_campaign is the authoritative caller."""
    raise SystemExit(
        json.dumps(
            {
                "error": "grading_preflight is an internal campaign module; run freeze_campaign.py"
            }
        )
    )


if __name__ == "__main__":
    main()
