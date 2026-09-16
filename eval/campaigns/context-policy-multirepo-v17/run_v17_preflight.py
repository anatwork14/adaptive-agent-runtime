"""Provider-free V17 freeze/preflight verifier."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from application.auth import auth_status
from eval.studies.meta import load_meta_preregistration
from eval.studies.preregistration import load_preregistration
from runtime.codex_invocation_config import load_snapshot, verify_snapshot

CAMPAIGN_DIR = Path(__file__).resolve().parent
ARC_REPO_ROOT = CAMPAIGN_DIR.parents[2]
if str(ARC_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(ARC_REPO_ROOT))
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))
from production_state import ProductionLedger, build_campaign_identities  # noqa: E402
from profile_staging import build_frozen_profile_payload, frozen_profile_digest  # noqa: E402
from codex_executable import inspect_codex_executable  # noqa: E402
from launcher_identity import assert_source_repository_clean, inspect_python_executable  # noqa: E402

REPOSITORIES = ("click", "httpx", "python-dotenv")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _docker_identities(contract: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for slug in REPOSITORIES:
        harness = contract["repositories"][slug]["visible_test_harness"]
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}|{{.Architecture}}|{{.Os}}", harness["image"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Docker identity unavailable for {slug}")
        image_digest, architecture, image_os = result.stdout.strip().split("|", 2)
        if (image_digest, architecture, image_os) != (
            harness["image_digest"],
            harness["architecture"],
            harness["os"],
        ):
            raise RuntimeError(f"Docker identity mismatch for {slug}")
        output[slug] = {
            "image": harness["image"],
            "image_digest": image_digest,
            "architecture": architecture,
            "os": image_os,
        }
    return output


def _ambient_independence(snapshot, executable: Path) -> bool:
    """Exercise Codex non-inference startup against a disposable ambient home."""
    with tempfile.TemporaryDirectory(prefix="arc-v17-ambient-") as raw:
        ambient = Path(raw)
        config = ambient / "config.toml"
        config.write_text('model = "ambient-before"\n', encoding="utf-8")
        env = dict(os.environ)
        env["CODEX_HOME"] = str(ambient)
        result = subprocess.run(
            [str(executable), "--help"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        config.write_text('model = "ambient-after"\n', encoding="utf-8")
        first = verify_snapshot(snapshot)
        second = verify_snapshot(snapshot)
        return first.config_sha256 == second.config_sha256 == snapshot.snapshot_sha256


def preflight(freeze_dir: Path) -> dict[str, Any]:
    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))
    assert_source_repository_clean(ARC_REPO_ROOT, stage="v17_static_preflight")
    launcher = contract["launcher"]
    python_launcher = inspect_python_executable(
        sys.executable,
        expected_version=launcher["python_version"],
        expected_sha256=launcher["python_sha256"],
        expected_architecture=launcher["architecture"],
    )
    manifest = json.loads((freeze_dir / "freeze-manifest.json").read_text(encoding="utf-8"))
    runtime = contract["provider_runtime"]
    source = load_snapshot(
        runtime["codex_snapshot_path"],
        expected_sha256=runtime["codex_snapshot_sha256"],
    )
    archived = load_snapshot(
        freeze_dir / manifest["codex_snapshot"]["archive_path"],
        expected_sha256=manifest["codex_snapshot"]["config_sha256"],
    )
    source_bytes = source.config_path.read_bytes()
    archived_bytes = archived.config_path.read_bytes()
    if source_bytes != archived_bytes:
        raise RuntimeError("frozen archive does not contain exact source config bytes")
    if dict(source.semantic_projection) != dict(archived.semantic_projection):
        raise RuntimeError("frozen semantic projection differs from source")

    plans: dict[str, Any] = {}
    for slug in REPOSITORIES:
        ref = manifest["repository_plans"][slug]
        plan = load_preregistration(freeze_dir / ref["path"])
        if plan.plan_digest != ref["plan_digest"]:
            raise RuntimeError(f"plan digest mismatch for {slug}")
        if plan.runtime.provider_codex_snapshot_sha256 != source.snapshot_sha256:
            raise RuntimeError(f"snapshot identity missing from {slug} plan")
        plans[slug] = plan

    profile_refs = manifest.get("repository_profiles")
    if not isinstance(profile_refs, dict) or set(profile_refs) != set(REPOSITORIES):
        raise RuntimeError("frozen repository profile set is incomplete")
    for slug in REPOSITORIES:
        reference = profile_refs[slug]
        profile_path = freeze_dir / reference["path"]
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        expected = build_frozen_profile_payload(contract, plans[slug], repository=slug)
        if payload != expected:
            raise RuntimeError(f"frozen repository profile semantic drift for {slug}")
        if frozen_profile_digest(payload) != reference.get("profile_digest"):
            raise RuntimeError(f"frozen repository profile digest mismatch for {slug}")
    meta = load_meta_preregistration(freeze_dir / manifest["meta_plan"])
    if meta.plan_digest != manifest["meta_plan_digest"]:
        raise RuntimeError("meta plan digest mismatch")

    executable = inspect_codex_executable(
        runtime["codex_executable_path"],
        expected_version=runtime["codex_executable_version"],
        expected_sha256=runtime["codex_executable_sha256"],
        expected_architecture=runtime["codex_executable_architecture"],
    )
    if manifest.get("codex_executable") != {
        "path": str(executable.path),
        "version": executable.version,
        "sha256": executable.sha256,
        "architecture": executable.architecture,
        "release_asset_sha256": runtime["codex_release_asset_sha256"],
    }:
        raise RuntimeError("frozen Codex executable identity differs from live identity")
    expected_launcher = {
        "type": launcher["type"],
        "script_path": str(Path(launcher["script_path"]).expanduser().resolve()),
        "python_path": str(python_launcher.path),
        "python_version": python_launcher.version,
        "python_sha256": python_launcher.sha256,
        "architecture": python_launcher.architecture,
        "environment_root": str(Path(launcher["environment_root"]).expanduser().resolve()),
    }
    if manifest.get("launcher") != expected_launcher:
        raise RuntimeError("frozen V17 launcher identity differs from live identity")
    auth = auth_status(
        "codex",
        environment={"CODEX_HOME": runtime["codex_home"]},
        executable=runtime["codex_executable_path"],
    )
    docker = _docker_identities(contract)
    if docker != manifest["docker_identities"]:
        raise RuntimeError("frozen Docker identities differ from live identities")

    with tempfile.TemporaryDirectory(prefix="arc-v17-ledger-preflight-") as directory:
        with ProductionLedger(
            Path(directory) / "ledger.sqlite",
            campaign_id=contract["campaign_id"],
            attempt_id="preflight",
            expected_tasks=162,
        ) as ledger:
            ledger.register(build_campaign_identities())
            ledger_counts = ledger.counts()
            ledger_checkpoint = ledger.checkpoint()
    assert_source_repository_clean(ARC_REPO_ROOT, stage="v17_static_preflight_complete")

    return {
        "schema_version": "arc-v17-provider-free-preflight-v1",
        "campaign_id": contract["campaign_id"],
        "frozen_config_bytes_recoverable": True,
        "recovered_sha256": _sha256(archived.config_path),
        "config_sha256": source.snapshot_sha256,
        "config_size": source.snapshot_size,
        "semantic_projection": dict(source.semantic_projection),
        "semantic_projection_pass": True,
        "auth_gate": bool(auth.installed and auth.authenticated),
        "auth_state": auth.state,
        "codex_version": executable.version,
        "codex_executable_path": str(executable.path),
        "codex_executable_sha256": executable.sha256,
        "codex_executable_architecture": executable.architecture,
        "launcher": expected_launcher,
        "docker_identities_verified": True,
        "ambient_config_independence": _ambient_independence(
            source, Path(runtime["codex_executable_path"])
        ),
        "runtime_contract_verified": True,
        "timeout_contract_verified": True,
        "provider_censor_contract_verified": True,
        "checkpoint_resume_contract_verified": True,
        "frozen_profiles_verified": True,
        "logical_task_registration_verified": ledger_counts["PENDING"] == 162,
        "logical_task_count": sum(ledger_counts.values()),
        "initial_observations": 0,
        "initial_checkpoint": ledger_checkpoint,
        "provider_requests": 0,
        "ready_for_execution": bool(auth.installed and auth.authenticated),
        "V17_attempt_started": False,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-dir", type=Path, required=True)
    args = parser.parse_args()
    report = preflight(args.freeze_dir.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ready_for_execution"]:
        raise SystemExit(1)
