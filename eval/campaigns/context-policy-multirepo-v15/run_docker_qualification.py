"""Run frozen visible and task-scoped hidden Docker harnesses on disposable copies."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ARC_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ARC_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(ARC_REPO_ROOT))

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


def _image_platform(image: str) -> tuple[str, str]:
    process = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Architecture}}|{{.Os}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout or "image inspect failed").strip())
    architecture, image_os = process.stdout.strip().split("|", 1)
    return architecture, image_os


def _assert_probe(result, *, label: str, expected_exit: int = 0, timed_out: bool = False) -> dict[str, Any]:
    if result.exit_code != expected_exit or result.timed_out is not timed_out:
        raise RuntimeError(
            f"{label} probe failed: exit={result.exit_code}, timed_out={result.timed_out}, "
            f"stdout={result.stdout[-300:]!r}, stderr={result.stderr[-300:]!r}"
        )
    return {
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
    }


def _hidden_harness_health(result) -> bool:
    """Classify evaluator health without requiring the candidate to pass tasks."""
    output = (result.stdout + "\n" + result.stderr).lower()
    collection_or_runner_failure = any(
        marker in output
        for marker in (
            "error collecting",
            "importerror",
            "modulenotfounderror",
            "internalerror",
            "no tests ran",
        )
    )
    return not result.timed_out and result.exit_code in (0, 1) and not collection_or_runner_failure


def qualify(
    hidden_root: Path,
    repo_root: Path = REPO_ROOT,
    repo_overrides: dict[str, Path] | None = None,
) -> dict[str, Any]:
    contract = _contract()
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="arc-v15-docker-qualification-") as directory:
        disposable_root = Path(directory)
        for slug in ("click", "httpx", "python-dotenv"):
            repository = contract["repositories"][slug]
            harness = repository["visible_test_harness"]
            clone = disposable_root / slug
            source_repo = (repo_overrides or {}).get(slug, repo_root / slug)
            _clone(source_repo, clone)
            runner = SandboxRunner(
                clone,
                network_enabled=bool(harness["network_enabled"]),
                timeout_seconds=int(harness["timeout_seconds"]),
                image=harness["image"],
                image_digest=harness["image_digest"],
                tmpfs_noexec=not bool(harness["tmpfs_exec"]),
            )
            identity = runner.verify_available()
            actual_architecture, actual_os = _image_platform(harness["image"])
            if (actual_architecture, actual_os) != (
                harness["architecture"],
                harness["os"],
            ):
                raise RuntimeError(
                    f"{slug} image platform drift: expected={harness['architecture']}|{harness['os']}, "
                    f"actual={actual_architecture}|{actual_os}"
                )
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
            write_marker = clone / ".arc-v15-write-probe"
            write_probe = runner.run_command(
                ["python", "-c", "from pathlib import Path; Path('/workspace/.arc-v15-write-probe').write_text('ok')"],
            )
            _assert_probe(write_probe, label="workspace-write")
            if write_marker.read_text(encoding="utf-8") != "ok":
                raise RuntimeError(f"{slug} workspace write did not propagate")
            write_marker.unlink()

            root_read_only = runner.run_command(
                ["python", "-c", "from pathlib import Path; Path('/opt/.arc-v15-readonly-probe').write_text('bad')"],
            )
            _assert_probe(root_read_only, label="root-read-only", expected_exit=1)

            network_probe = runner.run_command(
                [
                    "python",
                    "-c",
                    "import socket; s=socket.socket(); s.settimeout(1); "
                    "s.connect(('example.com', 80)); raise SystemExit('network reachable')",
                ],
            )
            _assert_probe(network_probe, label="network-isolation", expected_exit=1)

            agent_visibility = runner.run_command(
                [
                    "python",
                    "-c",
                    "import os; paths=['/arc-hidden-tests','/Users/teobun/arc-secure'," 
                    "'/Users/teobun/.codex','/var/run/docker.sock']; "
                    "assert not any(os.path.exists(p) for p in paths), paths; "
                    "mounts=open('/proc/self/mountinfo').read(); "
                    "assert '/Users/teobun' not in mounts and 'arc-secure' not in mounts",
                ],
            )
            _assert_probe(agent_visibility, label="agent-visibility")

            io_probe = runner.run_command(
                ["sh", "-c", "printf stdout-marker; printf stderr-marker >&2; exit 7"],
            )
            io_report = _assert_probe(io_probe, label="stdio-exit", expected_exit=7)
            if io_report["stdout"] != "stdout-marker" or io_report["stderr"] != "stderr-marker":
                raise RuntimeError(f"{slug} stdout/stderr propagation drift")

            timeout_probe = runner.run_command(
                ["python", "-c", "import time; time.sleep(2)"],
                timeout=1,
            )
            timeout_report = _assert_probe(timeout_probe, label="timeout", expected_exit=-1, timed_out=True)
            cleanup = ""
            cleanup_deadline = time.monotonic() + 5.0
            while time.monotonic() < cleanup_deadline:
                cleanup = subprocess.run(
                    ["docker", "ps", "-q", "--filter", f"ancestor={harness['image']}"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                if not cleanup:
                    break
                time.sleep(0.1)
            if cleanup:
                raise RuntimeError(f"{slug} timed-out container was not cleaned up")
            results[slug] = {
                "image": harness["image"],
                "expected_image_digest": harness["image_digest"],
                "actual_image_digest": identity["actual_image_digest"],
                "architecture": actual_architecture,
                "os": actual_os,
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
                    "task_passed": hidden.exit_code == 0 and not hidden.timed_out,
                    "harness_health": _hidden_harness_health(hidden),
                    "workspace_read_only": True,
                },
                "workspace_write": True,
                "root_read_only": True,
                "network_isolated": True,
                "hidden_root_isolated": True,
                "stdio_exit_propagation": io_report,
                "timeout": timeout_report,
                "process_cleanup": True,
            }
    return {
        "schema_version": "arc-v15-docker-qualification-v2",
        "campaign_id": contract["campaign_id"],
        "repositories": results,
        "all_image_identities_verified": all(
            item["sandbox_identity_verified"] for item in results.values()
        ),
        "all_visible_passed": all(item["visible"]["passed"] for item in results.values()),
        "all_hidden_task_results_passed": all(
            item["hidden"]["task_passed"] for item in results.values()
        ),
        "all_hidden_harness_health_passed": all(
            item["hidden"]["harness_health"] for item in results.values()
        ),
        "qualification_semantics": "HARNESS_HEALTH",
        "all_security_probes_passed": all(
            all(
                item[key] is True
                for key in (
                    "workspace_write",
                    "root_read_only",
                    "network_isolated",
                    "hidden_root_isolated",
                    "process_cleanup",
                )
            )
            for item in results.values()
        ),
        "provider_execution_started": False,
        "benchmark_attempt_created": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hidden-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--python-dotenv-repo", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    overrides = (
        {"python-dotenv": args.python_dotenv_repo.resolve()}
        if args.python_dotenv_repo is not None
        else None
    )
    result = qualify(args.hidden_root.resolve(), args.repo_root.resolve(), overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
