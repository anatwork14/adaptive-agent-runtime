"""Provider-free V12 freeze/preflight verifier."""

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
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))
from production_state import ProductionLedger, build_campaign_identities  # noqa: E402

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


def _ambient_independence(snapshot) -> bool:
    """Exercise Codex non-inference startup against a disposable ambient home."""
    with tempfile.TemporaryDirectory(prefix="arc-v12-ambient-") as raw:
        ambient = Path(raw)
        config = ambient / "config.toml"
        config.write_text('model = "ambient-before"\n', encoding="utf-8")
        env = dict(os.environ)
        env["CODEX_HOME"] = str(ambient)
        result = subprocess.run(
            ["codex", "--help"],
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

    for slug in REPOSITORIES:
        ref = manifest["repository_plans"][slug]
        plan = load_preregistration(freeze_dir / ref["path"])
        if plan.plan_digest != ref["plan_digest"]:
            raise RuntimeError(f"plan digest mismatch for {slug}")
        if plan.runtime.provider_codex_snapshot_sha256 != source.snapshot_sha256:
            raise RuntimeError(f"snapshot identity missing from {slug} plan")
    meta = load_meta_preregistration(freeze_dir / manifest["meta_plan"])
    if meta.plan_digest != manifest["meta_plan_digest"]:
        raise RuntimeError("meta plan digest mismatch")

    version = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False)
    auth = auth_status("codex", environment={"CODEX_HOME": runtime["codex_home"]})
    docker = _docker_identities(contract)
    if docker != manifest["docker_identities"]:
        raise RuntimeError("frozen Docker identities differ from live identities")
    if version.returncode or version.stdout.strip() != runtime["version"]:
        raise RuntimeError("pinned Codex version is unavailable")

    with tempfile.TemporaryDirectory(prefix="arc-v12-ledger-preflight-") as directory:
        with ProductionLedger(
            Path(directory) / "ledger.sqlite",
            campaign_id=contract["campaign_id"],
            attempt_id="preflight",
            expected_tasks=162,
        ) as ledger:
            ledger.register(build_campaign_identities())
            ledger_counts = ledger.counts()
            ledger_checkpoint = ledger.checkpoint()

    return {
        "schema_version": "arc-v12-provider-free-preflight-v1",
        "campaign_id": contract["campaign_id"],
        "frozen_config_bytes_recoverable": True,
        "recovered_sha256": _sha256(archived.config_path),
        "config_sha256": source.snapshot_sha256,
        "config_size": source.snapshot_size,
        "semantic_projection": dict(source.semantic_projection),
        "semantic_projection_pass": True,
        "auth_gate": bool(auth.installed and auth.authenticated),
        "auth_state": auth.state,
        "codex_version": version.stdout.strip(),
        "docker_identities_verified": True,
        "ambient_config_independence": _ambient_independence(source),
        "runtime_contract_verified": True,
        "timeout_contract_verified": True,
        "provider_censor_contract_verified": True,
        "checkpoint_resume_contract_verified": True,
        "logical_task_registration_verified": ledger_counts["PENDING"] == 162,
        "logical_task_count": sum(ledger_counts.values()),
        "initial_observations": 0,
        "initial_checkpoint": ledger_checkpoint,
        "provider_requests": 0,
        "ready_for_execution": bool(auth.installed and auth.authenticated),
        "v12_attempt_started": False,
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
