"""Freeze the complete public/private contract for context-policy-multirepo-v6.

This command performs no provider inference. It configures the canonical ARC
profile in three pinned repository clones, verifies the private hidden-test tree
digests, freezes one shared runtime lock, writes three self-digesting repository
preregistrations, and finally freezes the cross-repository meta-study plan.

Run it only after installing the intended Codex CLI build. Authentication is not
required for freezing; authenticated execution happens strictly afterwards.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

CAMPAIGN_DIR = Path(__file__).resolve().parent
ARC_REPO_ROOT = CAMPAIGN_DIR.parents[2]
if str(ARC_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(ARC_REPO_ROOT))
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))

from runtime_lock import freeze as freeze_runtime_lock  # noqa: E402
from runtime_lock import verify as verify_runtime_lock  # noqa: E402

from application.config import AgentProfile, ConfigStore  # noqa: E402
from eval.io import load_manifest  # noqa: E402
from eval.studies.meta import (  # noqa: E402
    create_meta_preregistration,
    save_meta_preregistration,
)
from eval.studies.preregistration import (  # noqa: E402
    create_preregistration,
    save_preregistration,
    tree_digest,
)
from isolation.container import SandboxRunner, SandboxUnavailable  # noqa: E402

BASELINES = ("b3", "b5", "b7")
REPOSITORY_ORDER = ("click", "httpx", "python-dotenv")


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git command failed").strip()
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {detail}")
    return proc.stdout.strip()


def _load_contract() -> dict[str, Any]:
    return json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))


def _validate_timeout_contract(contract: dict[str, Any]) -> int:
    if contract.get("campaign_id") != "context-policy-multirepo-v6":
        raise SystemExit("V6 campaign contract identity is invalid")
    if contract.get("parent_campaign") != "context-policy-multirepo-v5":
        raise SystemExit("V6 parent campaign must be context-policy-multirepo-v5")
    if (
        contract.get("scientific_core_preserved") is not True
        or contract.get("scientific_change") is not False
        or contract.get("apparatus_change_only") is not True
    ):
        raise SystemExit("V6 scientific contract must declare an apparatus-only change")
    timeout = int(contract["shared_protocol"]["provider_execution_timeout_seconds"])
    expected_policy = {
        "timeout_seconds": 600,
        "applies_to": ["B3", "B5", "B7"],
        "per_task_override": False,
        "per_repetition_override": False,
        "dynamic_extension": False,
        "retry_on_timeout": False,
    }
    if (
        timeout != 600
        or contract["provider_runtime"].get("provider_execution_timeout_seconds") != 600
        or contract.get("provider_execution_policy") != expected_policy
    ):
        raise SystemExit("V6 provider execution timeout policy must preserve 600 seconds")
    harness_timeouts = {
        int(item["visible_test_harness"]["timeout_seconds"])
        for item in contract["repositories"].values()
    }
    if harness_timeouts != {180}:
        raise SystemExit("V6 Docker harness timeout must preserve 180 seconds")
    provider_runtime = contract["provider_runtime"]
    if provider_runtime.get("codex_home") != "/Users/teobun/arc-secure/codex-v4-home":
        raise SystemExit("V6 Codex home must preserve the canonical subscription home")
    if provider_runtime.get("codex_config_path") != (
        "/Users/teobun/arc-secure/codex-v4-home/config.toml"
    ):
        raise SystemExit("V6 Codex config must preserve the canonical frozen config.toml")
    config_digest = provider_runtime.get("codex_config_sha256")
    if not isinstance(config_digest, str) or len(config_digest) != 64:
        raise SystemExit("V6 Codex config SHA-256 must be a 64-character hex digest")
    trusted_workspaces = provider_runtime.get("trusted_workspaces")
    if not isinstance(trusted_workspaces, list) or not trusted_workspaces:
        raise SystemExit("V6 Codex contract must declare trusted workspaces")
    strategy = provider_runtime.get("invocation_home_strategy")
    if not isinstance(strategy, dict) or strategy.get("mode") != "ephemeral_snapshot":
        raise SystemExit("V6 Codex contract must use the qualified ephemeral snapshot strategy")
    if provider_runtime.get("auth_mode") != "chatgpt_subscription":
        raise SystemExit("V6 provider auth mode must remain ChatGPT subscription")
    permitted = provider_runtime.get("environment_allowlist", {}).get("provider_permitted_keys", [])
    if any("API_KEY" in str(key) or "ACCESS_TOKEN" in str(key) for key in permitted):
        raise SystemExit("V6 provider environment must not permit API-key or access-token variables")
    return timeout


def _validate_repo(repo: Path, expected_commit: str) -> None:
    if not repo.is_dir():
        raise SystemExit(f"repository directory does not exist: {repo}")
    actual = _run_git(repo, "rev-parse", "HEAD")
    if actual != expected_commit:
        raise SystemExit(
            f"repository HEAD mismatch for {repo}: expected={expected_commit}, actual={actual}"
        )
    status = _run_git(repo, "status", "--porcelain")
    if status:
        raise SystemExit(f"repository must be clean before freeze: {repo}\n{status}")


def _profile(contract: dict[str, Any]) -> AgentProfile:
    payload = contract["provider_profile"]
    return AgentProfile(
        name=payload["name"],
        provider=payload["provider"],
        model=payload["model"],
        role=payload["role"],
        capabilities=list(payload["capabilities"]),
        env_allow=list(payload["env_allow"]),
        command_override=payload["command_override"],
        codex_home=contract["provider_runtime"]["codex_home"],
        codex_config_path=contract["provider_runtime"]["codex_config_path"],
        max_concurrency=1,
    )


def _configure_repo(repo: Path, slug: str, contract: dict[str, Any]) -> tuple[Any, AgentProfile]:
    protocol = contract["shared_protocol"]
    repository_contract = contract["repositories"][slug]
    profile = _profile(contract)
    store = ConfigStore(repo)
    config = store.load(contract["campaign_id"])
    config.project_id = contract["campaign_id"]
    config.default_agent = profile.name
    config.hard_task_usd = float(protocol["hard_task_usd"])
    config.hard_project_usd = float(protocol["hard_project_usd"])
    config.provider_execution_timeout_seconds = _validate_timeout_contract(contract)
    harness = repository_contract["visible_test_harness"]
    config.visible_test_cmd = list(harness["command"])
    config.visible_test_harness = dict(harness)
    config.agents[profile.name] = profile
    store.save(config)
    return config, profile


def _manifest_triplet(slug: str) -> list[Any]:
    paths = [CAMPAIGN_DIR / slug / f"{baseline}.yaml" for baseline in BASELINES]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("missing campaign manifests: " + ", ".join(map(str, missing)))
    return [load_manifest(path) for path in paths]


def _verify_hidden_tree(slug: str, hidden_root: Path, expected: str) -> Path:
    hidden = hidden_root / slug
    actual = tree_digest(hidden)
    if actual != expected:
        raise SystemExit(
            f"hidden-test digest mismatch for {slug}: expected={expected}, actual={actual}"
        )
    return hidden


def freeze_campaign(
    repos: dict[str, Path],
    *,
    hidden_root: Path,
    output_dir: Path,
) -> Path:
    contract = _load_contract()
    timeout_seconds = _validate_timeout_contract(contract)
    protocol = contract["shared_protocol"]
    repository_contracts = contract["repositories"]

    if output_dir.exists():
        raise SystemExit(f"refusing to overwrite campaign freeze directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    # Fail before writing anything if a public repo or private grader tree drifted.
    hidden_dirs: dict[str, Path] = {}
    for slug in REPOSITORY_ORDER:
        repo = repos[slug].resolve()
        expected = repository_contracts[slug]
        _validate_repo(repo, expected["commit"])
        hidden_dirs[slug] = _verify_hidden_tree(
            slug,
            hidden_root.resolve(),
            expected["hidden_tree_sha256"],
        )

    tmp = output_dir.with_name(output_dir.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.mkdir(parents=False, exist_ok=False)
    try:
        configured: dict[str, tuple[Any, AgentProfile]] = {}
        for slug in REPOSITORY_ORDER:
            configured[slug] = _configure_repo(repos[slug].resolve(), slug, contract)

        for slug in REPOSITORY_ORDER:
            harness = configured[slug][0].visible_test_harness
            if not harness:
                raise SystemExit(f"V6 Docker harness is missing for {slug}")
            try:
                sandbox = SandboxRunner(
                    repos[slug].resolve(),
                    network_enabled=bool(harness.get("network_enabled", False)),
                    timeout_seconds=int(harness.get("timeout_seconds", 120)),
                    image=harness.get("image"),
                    image_digest=harness.get("image_digest"),
                    tmpfs_noexec=not bool(harness.get("tmpfs_exec", False)),
                )
                sandbox_report = sandbox.verify_available()
            except SandboxUnavailable as exc:
                raise SystemExit(f"V6 Docker identity unavailable for {slug}: {exc}") from exc
            if sandbox_report.get("ready") is not True or sandbox_report.get(
                "actual_image_digest"
            ) != harness.get("image_digest"):
                raise SystemExit(
                    f"V6 Docker identity mismatch for {slug}: "
                    f"expected={harness.get('image_digest')}, "
                    f"actual={sandbox_report.get('actual_image_digest')}"
                )

        runtime_lock = tmp / "runtime-lock.json"
        freeze_runtime_lock(
            repos[REPOSITORY_ORDER[0]].resolve(),
            contract["provider_profile"]["name"],
            runtime_lock,
            ARC_REPO_ROOT,
            provider_execution_timeout_seconds=timeout_seconds,
        )
        for slug in REPOSITORY_ORDER:
            verify_runtime_lock(
                repos[slug].resolve(),
                contract["provider_profile"]["name"],
                runtime_lock,
                provider_execution_timeout_seconds=timeout_seconds,
            )

        plans = []
        plan_paths: dict[str, str] = {}
        for slug in REPOSITORY_ORDER:
            repo_contract = repository_contracts[slug]
            config, profile = configured[slug]
            manifests = _manifest_triplet(slug)
            if {manifest.repo_commit for manifest in manifests} != {repo_contract["commit"]}:
                raise SystemExit(f"manifest commit drift detected for {slug}")
            if {manifest.benchmark_id for manifest in manifests} != {repo_contract["benchmark_id"]}:
                raise SystemExit(f"manifest benchmark_id drift detected for {slug}")
            plan = create_preregistration(
                manifests,
                repos[slug].resolve(),
                study_id=repo_contract["study_id"],
                provider=profile.provider,
                profile_role=profile.role,
                profile_capabilities=profile.capabilities,
                visible_test_cmd=config.visible_test_cmd,
                visible_test_harness=config.visible_test_harness,
                hard_project_usd=config.hard_project_usd,
                hidden_test_dir=hidden_dirs[slug],
                verification_level=protocol["verification_level"],
                repeats=int(protocol["repeats"]),
                bootstrap_samples=int(protocol["bootstrap_samples"]),
                ci=float(protocol["ci"]),
                exclusions=list(protocol["exclusions"]),
                provider_execution_timeout_seconds=timeout_seconds,
                provider_codex_home=profile.codex_home,
                provider_codex_config_path=profile.codex_config_path,
                provider_codex_config_sha256=contract["provider_runtime"]["codex_config_sha256"],
            )
            plan_path = tmp / f"{slug}-context-policy-v6.json"
            save_preregistration(plan_path, plan)
            plans.append(plan)
            plan_paths[slug] = plan_path.name

        meta = create_meta_preregistration(
            plans,
            meta_id=contract["campaign_id"],
            bootstrap_samples=int(protocol["meta_bootstrap_samples"]),
            ci=float(protocol["meta_ci"]),
            random_seed=int(protocol["meta_random_seed"]),
        )
        meta_path = tmp / f"{contract['campaign_id']}.json"
        save_meta_preregistration(meta_path, meta)

        lock_payload = json.loads(runtime_lock.read_text(encoding="utf-8"))
        expected_runtime = {
            "provider": contract["provider_profile"]["provider"],
            "model": contract["provider_profile"]["model"],
            "role": contract["provider_profile"]["role"],
            "effective_argv_sha256": contract["provider_profile"]["effective_argv_sha256"],
            "provider_cli_version": contract["provider_runtime"]["version"],
            "provider_execution_timeout_seconds": timeout_seconds,
            "auth_mode": contract["provider_runtime"]["auth_mode"],
            "codex_home": contract["provider_runtime"]["codex_home"],
            "codex_config_path": contract["provider_runtime"]["codex_config_path"],
            "codex_config_sha256": contract["provider_runtime"]["codex_config_sha256"],
        }
        runtime_mismatches = [
            key for key, expected in expected_runtime.items() if lock_payload.get(key) != expected
        ]
        if runtime_mismatches:
            raise SystemExit(
                "V6 runtime identity differs from the public contract: "
                + ", ".join(runtime_mismatches)
            )
        freeze_manifest = {
            "campaign_id": contract["campaign_id"],
            "arc_commit": lock_payload["arc_commit"],
            "runtime_lock": runtime_lock.name,
            "runtime_lock_digest": lock_payload["lock_digest"],
            "provider_cli_version": lock_payload["provider_cli_version"],
            "provider_execution_timeout_seconds": lock_payload[
                "provider_execution_timeout_seconds"
            ],
            "repository_plans": {
                slug: {
                    "path": plan_paths[slug],
                    "plan_digest": plans[index].plan_digest,
                    "repo_commit": plans[index].canonical_repo_commit,
                    "hidden_tests_digest": plans[index].runtime.hidden_tests_digest,
                }
                for index, slug in enumerate(REPOSITORY_ORDER)
            },
            "meta_plan": meta_path.name,
            "meta_plan_digest": meta.plan_digest,
            "provider_execution_started": False,
        }
        (tmp / "freeze-manifest.json").write_text(
            json.dumps(freeze_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.rename(output_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    print(f"campaign_freeze={output_dir.resolve()}")
    print(f"meta_plan_digest={meta.plan_digest}")
    print("provider_execution_started=false")
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--click-repo", type=Path, required=True)
    parser.add_argument("--httpx-repo", type=Path, required=True)
    parser.add_argument("--python-dotenv-repo", type=Path, required=True)
    parser.add_argument("--hidden-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    freeze_campaign(
        {
            "click": args.click_repo,
            "httpx": args.httpx_repo,
            "python-dotenv": args.python_dotenv_repo,
        },
        hidden_root=args.hidden_root,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
