"""Freeze V10 once, preserving V9 science and archiving exact Codex bytes."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.studies.meta import MetaStudyPlan, compute_meta_plan_digest, save_meta_preregistration
from eval.studies.preregistration import (
    PreregisteredStudy,
    compute_plan_digest,
    save_preregistration,
)
from runtime.codex_invocation_config import load_snapshot

CAMPAIGN_DIR = Path(__file__).resolve().parent
ARC_ROOT = CAMPAIGN_DIR.parents[2]
V9_FREEZE = Path("/Users/teobun/arc-secure/prereg/context-policy-multirepo-v9")
V10_FREEZE = Path("/Users/teobun/arc-secure/prereg/context-policy-multirepo-v10")
REPOSITORIES = ("click", "httpx", "python-dotenv")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ARC_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SystemExit((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _replace_v9(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("context-policy-multirepo-v9", "context-policy-multirepo-v10") \
            .replace("context-policy-click-v9", "context-policy-click-v10") \
            .replace("context-policy-httpx-v9", "context-policy-httpx-v10") \
            .replace("context-policy-python-dotenv-v9", "context-policy-python-dotenv-v10") \
            .replace("click-context-policy-v9", "click-context-policy-v10") \
            .replace("httpx-context-policy-v9", "httpx-context-policy-v10") \
            .replace("python-dotenv-context-policy-v9", "python-dotenv-context-policy-v10")
    if isinstance(value, list):
        return [_replace_v9(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_v9(item) for key, item in value.items()}
    return value


def _verify_docker(contract: dict[str, Any]) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {}
    for slug in REPOSITORIES:
        harness = contract["repositories"][slug]["visible_test_harness"]
        image = str(harness["image"])
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}|{{.Architecture}}|{{.Os}}", image],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise SystemExit(f"Docker identity unavailable for {slug}")
        image_id, architecture, image_os = result.stdout.strip().split("|", 2)
        expected = harness["image_digest"]
        if image_id != expected or architecture != harness["architecture"] or image_os != harness["os"]:
            raise SystemExit(f"Docker identity mismatch for {slug}")
        identities[slug] = {
            "image": image,
            "image_digest": image_id,
            "architecture": architecture,
            "os": image_os,
        }
    return identities


def freeze() -> Path:
    if V10_FREEZE.exists():
        raise SystemExit(f"refusing to overwrite existing V10 freeze: {V10_FREEZE}")
    if _git("status", "--porcelain"):
        raise SystemExit("V10 source worktree must be clean before freeze")

    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))
    snapshot = load_snapshot(
        CAMPAIGN_DIR / "codex",
        expected_sha256=contract["provider_runtime"]["codex_snapshot_sha256"],
    )
    docker = _verify_docker(contract)
    cli_version = subprocess.run(["codex", "--version"], capture_output=True, text=True, check=False)
    if cli_version.returncode or cli_version.stdout.strip() != contract["provider_runtime"]["version"]:
        raise SystemExit("pinned Codex CLI version mismatch")

    V10_FREEZE.mkdir(parents=True)
    (V10_FREEZE / "campaign-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = V10_FREEZE / "codex"
    archive.mkdir()
    for name in ("config.toml", "config.toml.sha256", "config-manifest.json"):
        shutil.copyfile(CAMPAIGN_DIR / "codex" / name, archive / name)

    plans: dict[str, PreregisteredStudy] = {}
    for slug in REPOSITORIES:
        source_name = f"{slug}-context-policy-v9.json"
        if slug == "python-dotenv":
            source_name = "python-dotenv-context-policy-v9.json"
        payload = _replace_v9(json.loads((V9_FREEZE / source_name).read_text(encoding="utf-8")))
        payload["plan_digest"] = ""
        runtime = payload["runtime"]
        runtime.update(
            {
                "provider_codex_config_path": str(CAMPAIGN_DIR / "codex" / "config.toml"),
                "provider_codex_config_sha256": snapshot.snapshot_sha256,
                "provider_codex_snapshot_path": str(CAMPAIGN_DIR / "codex"),
                "provider_codex_snapshot_sha256": snapshot.snapshot_sha256,
                "provider_codex_snapshot_size": snapshot.snapshot_size,
            }
        )
        plan = PreregisteredStudy.model_validate(payload)
        plan = plan.model_copy(update={"plan_digest": compute_plan_digest(plan)})
        target = V10_FREEZE / f"{slug}-context-policy-v10.json"
        save_preregistration(target, plan)
        plans[slug] = plan

    meta_payload = _replace_v9(
        json.loads((V9_FREEZE / "context-policy-multirepo-v9.json").read_text(encoding="utf-8"))
    )
    meta_payload["meta_id"] = contract["campaign_id"]
    meta_payload["plan_digest"] = ""
    # Repository order is part of the V9 meta-study contract; update refs by
    # that stable order rather than parsing slugs from human-readable IDs.
    for item, slug in zip(meta_payload["repositories"], REPOSITORIES, strict=True):
        item.update(
            {
                "study_id": plans[slug].study_id,
                "benchmark_id": plans[slug].benchmark_id,
                "plan_digest": plans[slug].plan_digest,
            }
        )
    meta = MetaStudyPlan.model_validate(meta_payload)
    meta = meta.model_copy(update={"plan_digest": compute_meta_plan_digest(meta)})
    save_meta_preregistration(V10_FREEZE / "context-policy-multirepo-v10.json", meta)

    runtime = contract["provider_runtime"]
    lock = {
        "schema_version": "arc-empirical-runtime-lock-v10",
        "profile": contract["provider_profile"]["name"],
        "provider": contract["provider_profile"]["provider"],
        "model": contract["provider_profile"]["model"],
        "role": contract["provider_profile"]["role"],
        "capabilities": sorted(contract["provider_profile"]["capabilities"]),
        "effective_argv_sha256": contract["provider_profile"]["effective_argv_sha256"],
        "provider_cli_version": runtime["version"],
        "env_allow": [],
        "provider_execution_timeout_seconds": 600,
        "auth_mode": runtime["auth_mode"],
        "codex_home": runtime["codex_home"],
        "codex_config_path": str(CAMPAIGN_DIR / "codex" / "config.toml"),
        "codex_config_sha256": snapshot.snapshot_sha256,
        "codex_config_size": snapshot.snapshot_size,
        "codex_snapshot_path": str(CAMPAIGN_DIR / "codex"),
        "codex_snapshot_sha256": snapshot.snapshot_sha256,
        "arc_commit": _git("rev-parse", "HEAD"),
        "arc_worktree_clean": True,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "lock_digest": "",
    }
    lock["lock_digest"] = hashlib.sha256(
        json.dumps({**lock, "lock_digest": ""}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (V10_FREEZE / "runtime-lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    manifest = {
        "schema_version": "arc-freeze-manifest-v10",
        "campaign_id": contract["campaign_id"],
        "parent_campaign": contract["parent_campaign"],
        "arc_commit": lock["arc_commit"],
        "provider_execution_started": False,
        "provider_cli_version": runtime["version"],
        "provider_execution_timeout_seconds": 600,
        "runtime_lock": "runtime-lock.json",
        "runtime_lock_digest": lock["lock_digest"],
        "meta_plan": "context-policy-multirepo-v10.json",
        "meta_plan_digest": meta.plan_digest,
        "campaign_contract": "campaign-contract.json",
        "campaign_contract_sha256": _sha256(V10_FREEZE / "campaign-contract.json"),
        "codex_snapshot": {
            "source_path": str(CAMPAIGN_DIR / "codex"),
            "archive_path": "codex",
            "config_path": "codex/config.toml",
            "config_sha256": snapshot.snapshot_sha256,
            "config_size": snapshot.snapshot_size,
            "semantic_projection": dict(snapshot.semantic_projection),
            "credentials_in_archive": False,
        },
        "docker_identities": docker,
        "repository_plans": {
            slug: {
                "path": f"{slug}-context-policy-v10.json",
                "plan_digest": plans[slug].plan_digest,
                "hidden_tests_digest": plans[slug].runtime.hidden_tests_digest,
            }
            for slug in REPOSITORIES
        },
        "operational_fault_policy": contract["operational_fault_policy"],
    }
    (V10_FREEZE / "freeze-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"freeze_dir={V10_FREEZE}")
    print(f"config_sha256={snapshot.snapshot_sha256}")
    print(f"meta_plan_digest={meta.plan_digest}")
    return V10_FREEZE


if __name__ == "__main__":
    freeze()
