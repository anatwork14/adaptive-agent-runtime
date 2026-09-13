"""Run frozen visible and task-scoped hidden Docker harnesses on disposable copies."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from isolation.container import SandboxRunner

CAMPAIGN_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path("/Users/teobun/arc-study/repos")


def _contract() -> dict[str, Any]:
    return json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))


def _clone(source: Path, target: Path) -> None:
    process = subprocess.run(
        ["git", "clone", "--quiet", str(source), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout or "git clone failed").strip())


def qualify(hidden_root: Path, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    contract = _contract()
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="arc-v5-docker-qualification-") as directory:
        disposable_root = Path(directory)
        for slug in ("click", "httpx", "python-dotenv"):
            repository = contract["repositories"][slug]
            harness = repository["visible_test_harness"]
            clone = disposable_root / slug
            _clone(repo_root / slug, clone)
            runner = SandboxRunner(
                clone,
                network_enabled=bool(harness["network_enabled"]),
                timeout_seconds=int(harness["timeout_seconds"]),
                image=harness["image"],
                image_digest=harness["image_digest"],
                tmpfs_noexec=not bool(harness["tmpfs_exec"]),
            )
            identity = runner.verify_available()
            visible = runner.run_command(
                list(harness["command"]),
                env_vars=dict(harness["environment"]),
            )
            hidden = runner.run_command(
                list(harness["hidden_command"]),
                env_vars=dict(harness["hidden_environment"]),
                read_only_mounts={"/arc-hidden-tests": hidden_root / slug},
                workspace_read_only=True,
            )
            results[slug] = {
                "image": harness["image"],
                "expected_image_digest": harness["image_digest"],
                "actual_image_digest": identity["actual_image_digest"],
                "sandbox_identity_verified": identity["ready"]
                and identity["actual_image_digest"] == harness["image_digest"],
                "visible": {
                    "exit_code": visible.exit_code,
                    "timed_out": visible.timed_out,
                    "duration_ms": visible.duration_ms,
                    "passed": visible.exit_code == 0 and not visible.timed_out,
                },
                "hidden": {
                    "exit_code": hidden.exit_code,
                    "timed_out": hidden.timed_out,
                    "duration_ms": hidden.duration_ms,
                    "passed": hidden.exit_code == 0 and not hidden.timed_out,
                    "workspace_read_only": True,
                },
            }
    return {
        "schema_version": "arc-v5-docker-qualification-v1",
        "campaign_id": contract["campaign_id"],
        "repositories": results,
        "all_image_identities_verified": all(
            item["sandbox_identity_verified"] for item in results.values()
        ),
        "all_visible_passed": all(item["visible"]["passed"] for item in results.values()),
        "all_hidden_passed": all(item["hidden"]["passed"] for item in results.values()),
        "provider_execution_started": False,
        "benchmark_attempt_created": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hidden-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.hidden_root.resolve(), args.repo_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
