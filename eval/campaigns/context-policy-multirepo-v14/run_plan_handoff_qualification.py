"""Provider-free qualification of the V14 nested run-plan handoff.

This deliberately invokes the same ``cli.bootstrap benchmark run-plan``
subprocess used by the campaign.  The CLI validates the frozen provider
identity and then exits before constructing a benchmark runner, so this check
cannot create a measurement or send a provider request.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ARC_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(ARC_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(ARC_REPO_ROOT))

from application.config import ConfigStore  # noqa: E402
from eval.io import load_manifest  # noqa: E402
from eval.studies.preregistration import (  # noqa: E402
    create_preregistration,
    save_preregistration,
)

CAMPAIGN_DIR = Path(__file__).resolve().parent


def _contract() -> dict[str, Any]:
    return json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))


def qualify(repo: Path, hidden_dir: Path, profile_path: Path) -> dict[str, Any]:
    contract = _contract()
    repo = repo.resolve()
    hidden_dir = hidden_dir.resolve()
    repository = contract["repositories"]["click"]
    config = ConfigStore.load_explicit(profile_path)
    profile = config.agents[contract["provider_profile"]["name"]].model_copy(
        update={
            "command_override": contract["provider_profile"]["command_override"],
            "codex_config_path": contract["provider_runtime"]["codex_config_path"],
            "codex_invocation_snapshot_path": contract["provider_runtime"]["codex_snapshot_path"],
            "codex_invocation_snapshot_sha256": contract["provider_runtime"]["codex_snapshot_sha256"],
            "codex_invocation_snapshot_size": contract["provider_runtime"]["codex_config_size"],
            "codex_invocation_manifest_path": contract["provider_runtime"]["codex_snapshot_manifest_path"],
            "codex_invocation_manifest_sha256": contract["provider_runtime"]["codex_snapshot_manifest_sha256"],
            "codex_invocation_codex_version": contract["provider_runtime"]["codex_snapshot_codex_version"],
            "codex_invocation_provider": contract["provider_runtime"]["codex_snapshot_provider"],
            "codex_invocation_authentication_required": contract["provider_runtime"]["codex_snapshot_authentication_required"],
            "codex_invocation_semantic_projection": contract["provider_runtime"]["codex_snapshot_semantic_projection"],
        }
    )
    manifests = [
        load_manifest(CAMPAIGN_DIR / "click" / f"{baseline}.yaml")
        for baseline in ("b3", "b5", "b7")
    ]
    protocol = contract["shared_protocol"]
    plan = create_preregistration(
        manifests,
        repo,
        study_id=repository["study_id"],
        provider=profile.provider,
        profile_role=profile.role,
        profile_capabilities=profile.capabilities,
        visible_test_cmd=config.visible_test_cmd,
        visible_test_harness=config.visible_test_harness,
        hard_project_usd=config.hard_project_usd,
        hidden_test_dir=hidden_dir,
        verification_level=protocol["verification_level"],
        repeats=int(protocol["repeats"]),
        bootstrap_samples=int(protocol["bootstrap_samples"]),
        ci=float(protocol["ci"]),
        exclusions=list(protocol["exclusions"]),
        provider_execution_timeout_seconds=int(protocol["provider_execution_timeout_seconds"]),
        provider_codex_home=profile.codex_home,
        provider_codex_config_path=profile.codex_config_path,
        provider_codex_config_sha256=contract["provider_runtime"]["codex_config_sha256"],
        provider_codex_snapshot_path=profile.codex_invocation_snapshot_path,
        provider_codex_snapshot_sha256=profile.codex_invocation_snapshot_sha256,
        provider_codex_snapshot_size=profile.codex_invocation_snapshot_size,
        provider_codex_manifest_path=profile.codex_invocation_manifest_path,
        provider_codex_manifest_sha256=profile.codex_invocation_manifest_sha256,
        provider_codex_version=profile.codex_invocation_codex_version,
        provider_codex_provider=profile.codex_invocation_provider,
        provider_codex_authentication_required=profile.codex_invocation_authentication_required,
        provider_codex_semantic_projection=profile.codex_invocation_semantic_projection,
    )

    with tempfile.TemporaryDirectory(prefix="arc-v14-run-plan-handoff-") as directory:
        root = Path(directory)
        temp_repo = root / "repo"
        shutil.copytree(repo, temp_repo)
        ConfigStore(temp_repo).add_agent(profile, make_default=True)
        plan_path = save_preregistration(root / "click-context-policy-v14.json", plan)
        command = [
            sys.executable,
            "-m",
            "cli.bootstrap",
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            str(temp_repo),
            "--attempt-id",
            "qualification",
            "--output-root",
            str(root / "results"),
            "--workspace-root",
            str(root / "workspace"),
            "--hidden-test-dir",
            str(hidden_dir),
            "--production-profile",
            str(profile_path),
            "--qualification-only",
        ]
        process = subprocess.run(
            command,
            cwd=ARC_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = (process.stdout + process.stderr).strip()
        passed = (
            process.returncode == 0
            and "run_plan_provider_environment_handoff=VERIFIED" in combined
            and "provider_execution_started=false" in combined
        )
        report = {
            "schema_version": "arc-v14-run-plan-provider-handoff-qualification-v1",
            "campaign_id": contract["campaign_id"],
            "repository": "click",
            "command": command,
            "returncode": process.returncode,
            "provider_environment_contract_verified": passed,
            "run_plan_provider_environment_handoff_verified": passed,
            "provider_codex_home": profile.codex_home,
            "profile_path": str(profile_path),
            "provider_codex_config_path": profile.codex_config_path,
            "provider_codex_config_sha256": contract["provider_runtime"]["codex_config_sha256"],
            "provider_codex_snapshot_sha256": contract["provider_runtime"]["codex_snapshot_sha256"],
            "provider_execution_started": False,
            "provider_turn": False,
            "scientific_measurement_created": False,
            "output": combined,
        }
        if not passed:
            raise RuntimeError(json.dumps(report, indent=2, sort_keys=True))
        return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--hidden-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.repo, args.hidden_dir, args.profile), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
