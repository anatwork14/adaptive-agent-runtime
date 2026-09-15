"""Provider-free qualification of the V9 nested run-plan handoff.

This deliberately invokes the same ``cli.bootstrap benchmark run-plan``
subprocess used by the campaign.  The CLI validates the frozen provider
identity and then exits before constructing a benchmark runner, so this check
cannot create a measurement or send a provider request.
"""

from __future__ import annotations

import argparse
import json
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
EXPECTED_CONFIG_SHA = "f94270078be62298be8a9ed92fb13fcb0a5480521943493df59108e5370bce10"


def _contract() -> dict[str, Any]:
    return json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))


def qualify(repo: Path, hidden_dir: Path) -> dict[str, Any]:
    contract = _contract()
    repo = repo.resolve()
    hidden_dir = hidden_dir.resolve()
    repository = contract["repositories"]["click"]
    config = ConfigStore(repo).load()
    profile = config.agents[contract["provider_profile"]["name"]]
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
    )

    with tempfile.TemporaryDirectory(prefix="arc-v9-run-plan-handoff-") as directory:
        root = Path(directory)
        plan_path = save_preregistration(root / "click-context-policy-v9.json", plan)
        command = [
            sys.executable,
            "-m",
            "cli.bootstrap",
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            str(repo),
            "--attempt-id",
            "qualification",
            "--output-root",
            str(root / "results"),
            "--workspace-root",
            str(root / "workspace"),
            "--hidden-test-dir",
            str(hidden_dir),
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
            "schema_version": "arc-v9-run-plan-provider-handoff-qualification-v1",
            "campaign_id": contract["campaign_id"],
            "repository": "click",
            "command": command,
            "returncode": process.returncode,
            "provider_environment_contract_verified": passed,
            "run_plan_provider_environment_handoff_verified": passed,
            "provider_codex_home": profile.codex_home,
            "provider_codex_config_path": profile.codex_config_path,
            "provider_codex_config_sha256": contract["provider_runtime"]["codex_config_sha256"],
            "expected_provider_codex_config_sha256": EXPECTED_CONFIG_SHA,
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
    args = parser.parse_args()
    print(json.dumps(qualify(args.repo, args.hidden_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
