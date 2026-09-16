"""Preflight and execute the frozen context-policy-multirepo-v15 provider study.

The freeze step fixes the scientific design. This command is the operational
boundary immediately before provider inference. It revalidates every frozen
contract, checks Codex authentication directly, refuses dirty/drifted source or
ARC worktrees, records one immutable campaign attempt, runs all three repository
studies through the public ARC CLI, exports them, and only then runs the frozen
hierarchical meta-analysis.

Nothing retries automatically. A failed attempt remains on disk and requires a
new explicit attempt ID plus the preregistered exclusion policy to justify any
replacement attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAMPAIGN_DIR = Path(__file__).resolve().parent
ARC_REPO_ROOT = CAMPAIGN_DIR.parents[2]
if str(ARC_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(ARC_REPO_ROOT))
if str(CAMPAIGN_DIR) not in sys.path:
    sys.path.insert(0, str(CAMPAIGN_DIR))

from run_plan_handoff_qualification import qualify as qualify_run_plan_handoff  # noqa: E402
from runtime_lock import verify as verify_runtime_lock  # noqa: E402

from application.agents import profile_invocation_config  # noqa: E402
from application.auth import auth_status  # noqa: E402
from application.config import ConfigStore  # noqa: E402
from eval.studies.meta import load_meta_preregistration  # noqa: E402
from eval.studies.preregistration import (  # noqa: E402
    load_preregistration,
    tree_digest,
    validate_execution_environment,
)
from isolation.container import SandboxRunner, SandboxUnavailable  # noqa: E402
from runtime.codex_invocation_config import load_snapshot  # noqa: E402
from profile_staging import (  # noqa: E402
    ProfileStagingError,
    build_frozen_profile_payload,
    frozen_profile_digest,
    load_staged_profile,
    stage_frozen_repository_profiles,
)
from codex_executable import inspect_codex_executable  # noqa: E402
from launcher_identity import (  # noqa: E402
    assert_source_repository_clean,
    inspect_python_executable,
)

SCHEMA = "arc-campaign-execution-v15"
REPOSITORY_ORDER = ("click", "httpx", "python-dotenv")
ATTEMPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

from production_state import (  # noqa: E402
    AttemptInitializationError,
    ProductionLedger,
    build_campaign_identities,
    initialize_production_attempt,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_launcher_identity(contract: dict[str, Any], *, phase: str) -> dict[str, Any]:
    launcher = contract["launcher"]
    identity = inspect_python_executable(
        sys.executable,
        expected_version=launcher["python_version"],
        expected_sha256=launcher["python_sha256"],
        expected_architecture=launcher["architecture"],
    )
    expected_path = Path(launcher["python_path"]).expanduser().resolve()
    if identity.path != expected_path:
        raise SystemExit(
            f"V15 launcher Python path mismatch at {phase}: "
            f"expected={expected_path}, actual={identity.path}"
        )
    return {
        "phase": phase,
        "python_path": str(identity.path),
        "python_version": identity.version,
        "python_sha256": identity.sha256,
        "architecture": identity.architecture,
        "script_path": str(Path(launcher["script_path"]).expanduser().resolve()),
        "environment_root": str(Path(launcher["environment_root"]).expanduser().resolve()),
        "verified": True,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tmp.open("r+") as handle:
        handle.flush()
        import os

        os.fsync(handle.fileno())
    tmp.replace(path)


def _production_metadata(plans: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for repository in REPOSITORY_ORDER:
        plan = plans[repository]
        for repetition in range(1, 7):
            for baseline in ("B3", "B5", "B7"):
                for task_index, task in enumerate(plan.manifests[0].tasks):
                    identity = f"{repository}/r{repetition}/{baseline}/{task.task_id}"
                    metadata[identity] = {
                        "plan_digest": plan.plan_digest,
                        "hidden_test_digest": plan.runtime.hidden_tests_digest,
                        "provider": "codex",
                        "model": str(plan.manifests[0].model),
                        "execution_mode": plan.manifests[0].execution_mode,
                        "timeout_seconds": int(plan.runtime.provider_execution_timeout_seconds or 600),
                        "baseline_order_index": ("B3", "B5", "B7").index(baseline),
                        "task_order_index": task_index,
                    }
    return metadata


def _frozen_profile_payloads(
    contract: dict[str, Any], plans: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Build the one campaign-authoritative profile object per repository."""
    return {
        repository: build_frozen_profile_payload(
            contract,
            plans[repository],
            repository=repository,
        )
        for repository in REPOSITORY_ORDER
    }


def _build_pre_execution_manifest(
    *,
    contract: dict[str, Any],
    report: dict[str, Any],
    freeze_manifest: dict[str, Any],
    meta: Any,
    plans: dict[str, Any],
    attempt_id: str,
    ledger_path: Path,
    checkpoint_path: Path,
) -> dict[str, Any]:
    runtime = contract["provider_runtime"]
    provider = contract["provider_profile"]
    return {
        "schema_version": "arc-v15-pre-execution-manifest",
        "campaign": contract["campaign_id"],
        "attempt": attempt_id,
        "timestamp": _now(),
        "V15_head": _run_git(ARC_REPO_ROOT, "rev-parse", "HEAD"),
        "codex_version": runtime["version"],
        "codex_executable_path": runtime["codex_executable_path"],
        "codex_executable_sha256": runtime["codex_executable_sha256"],
        "codex_executable_architecture": runtime["codex_executable_architecture"],
        "launcher_identity": report["launcher_identity"],
        "model": provider["model"],
        "reasoning": runtime["codex_snapshot_semantic_projection"].get("model_reasoning_effort"),
        "provider": provider["provider"],
        "preregistration_identity": contract["campaign_id"],
        "plan_digests": {slug: plans[slug].plan_digest for slug in REPOSITORY_ORDER},
        "meta_digest": meta.plan_digest,
        "runtime_lock_digest": report["runtime_lock_digest"],
        "immutable_codex_config_digest": runtime["codex_config_sha256"],
        "hidden_tree_digests": {
            slug: plans[slug].runtime.hidden_tests_digest for slug in REPOSITORY_ORDER
        },
        "docker_identities": freeze_manifest["docker_identities"],
        "logical_task_count": 162,
        "ledger_path": str(ledger_path),
        "ledger_schema": "V15-production-ledger-1",
        "checkpoint_path": str(checkpoint_path),
        "provider_classification_policy": "provider_evidence_before_infrastructure_timeout_model",
        "retry_policy": "one_registered_safe_provider-censor retry only",
        "measurement_policy": "completed requires durable measurement export",
        "profile_staging": report["profile_staging"],
        "host": __import__("platform").node(),
        "os": __import__("platform").system(),
        "architecture": __import__("platform").machine(),
    }


def _initialize_execution_boundary(
    *,
    contract: dict[str, Any],
    report: dict[str, Any],
    freeze_manifest: dict[str, Any],
    meta: Any,
    plans: dict[str, Any],
    execution_root: Path,
    attempt_id: str,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    ledger_path = execution_root / "production-ledger.sqlite"
    checkpoint_path = execution_root / "checkpoint.json"
    manifest_path = execution_root / "pre-execution-manifest.json"
    manifest = _build_pre_execution_manifest(
        contract=contract,
        report=report,
        freeze_manifest=freeze_manifest,
        meta=meta,
        plans=plans,
        attempt_id=attempt_id,
        ledger_path=ledger_path,
        checkpoint_path=checkpoint_path,
    )
    try:
        ledger = initialize_production_attempt(
            ledger_path=ledger_path,
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
            identities=build_campaign_identities(),
            campaign_id=contract["campaign_id"],
            attempt_id=attempt_id,
            expected_tasks=162,
            manifest=manifest,
            metadata_by_key=_production_metadata(plans),
        )
        snapshot = ledger.execution_boundary_snapshot(
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
        )
        ledger.close()
        if not snapshot["ready"]:
            raise AttemptInitializationError(snapshot["blocking_reason"] or "execution boundary is not ready")
    except Exception:
        raise
    return ledger_path, manifest_path, checkpoint_path, manifest


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
    timeout = int(contract["shared_protocol"]["provider_execution_timeout_seconds"])
    policy = contract.get("provider_execution_policy")
    if (
        timeout != 600
        or contract["provider_runtime"].get("provider_execution_timeout_seconds") != 600
        or not isinstance(policy, dict)
    ):
        raise SystemExit("V15 provider execution timeout policy must preserve 600 seconds")
    expected_policy = {
        "timeout_seconds": 600,
        "applies_to": ["B3", "B5", "B7"],
        "per_task_override": False,
        "per_repetition_override": False,
        "dynamic_extension": False,
        "retry_on_timeout": False,
    }
    if policy != expected_policy:
        raise SystemExit("V15 provider timeout policy drifted from the campaign contract")
    return timeout


def _validate_operational_policy(contract: dict[str, Any]) -> dict[str, Any]:
    policy = contract.get("operational_fault_policy")
    expected_states = [
        "PENDING", "RUNNING", "COMPLETED", "PROVIDER_CENSORED", "TIMEOUT",
        "MODEL_FAILED", "INFRASTRUCTURE_FAILED",
    ]
    if not isinstance(policy, dict):
        raise SystemExit("V15 operational fault policy is missing")
    if policy.get("observation_unit") != ["repository", "repetition", "baseline", "task"]:
        raise SystemExit("V15 observation unit drifted")
    if policy.get("states") != expected_states or policy.get("ledger") != "append_only_sqlite_atomic_task_state":
        raise SystemExit("V15 task-state or ledger policy drifted")
    if policy.get("max_provider_censor_retries_per_logical_task") != 1:
        raise SystemExit("V15 provider-censor retry bound drifted")
    if policy.get("safe_retry_requires") != {
        "model_output_generated": False,
        "tool_execution_started": False,
        "repository_modified": False,
    }:
        raise SystemExit("V15 safe-retry gate drifted")
    scoring = policy.get("scoring", {})
    if not scoring.get("aggregate_requires_all_required_tasks_completed") or not scoring.get("campaign_final_requires_all_required_logical_tasks_completed"):
        raise SystemExit("V15 scoring completeness gate drifted")
    return policy


def _validate_attempt_id(attempt_id: str) -> None:
    if not ATTEMPT_RE.fullmatch(attempt_id):
        raise SystemExit(
            "attempt-id must match [A-Za-z0-9][A-Za-z0-9._-]* and contain no path separators"
        )


def _provider_environment(contract: dict[str, Any]) -> dict[str, str]:
    """Return the only provider-home override permitted by the V15 contract."""
    return {"CODEX_HOME": str(contract["provider_runtime"]["codex_home"])}


def _validate_provider_runtime_identity(
    contract: dict[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    """Fail closed if the frozen provider home or non-secret config drifts."""
    runtime = contract["provider_runtime"]
    executable = inspect_codex_executable(
        runtime["codex_executable_path"],
        expected_version=runtime["codex_executable_version"],
        expected_sha256=runtime["codex_executable_sha256"],
        expected_architecture=runtime["codex_executable_architecture"],
    )
    expected_home = str(runtime["codex_home"])
    expected_snapshot = Path(str(runtime["codex_snapshot_path"])).resolve()
    actual_home = _provider_environment(contract)["CODEX_HOME"]
    if actual_home != expected_home:
        raise RuntimeError(
            f"provider runtime CODEX_HOME drift detected at {phase}: "
            f"expected={expected_home}, actual={actual_home}"
        )
    snapshot = load_snapshot(
        expected_snapshot,
        expected_sha256=str(runtime["codex_snapshot_sha256"]),
    )
    expected_manifest = Path(str(runtime["codex_snapshot_manifest_path"])).resolve()
    if snapshot.manifest_path != expected_manifest:
        raise RuntimeError(f"provider snapshot manifest path drift detected at {phase}")
    if snapshot.manifest_sha256 != runtime["codex_snapshot_manifest_sha256"]:
        raise RuntimeError(f"provider snapshot manifest digest drift detected at {phase}")
    if snapshot.codex_version != runtime["codex_snapshot_codex_version"]:
        raise RuntimeError(f"provider snapshot Codex version drift detected at {phase}")
    if snapshot.provider != runtime["codex_snapshot_provider"]:
        raise RuntimeError(f"provider snapshot provider drift detected at {phase}")
    if snapshot.authentication_required != runtime["codex_snapshot_authentication_required"]:
        raise RuntimeError(f"provider snapshot authentication policy drift detected at {phase}")
    if dict(snapshot.semantic_projection) != runtime["codex_snapshot_semantic_projection"]:
        raise RuntimeError(f"provider snapshot semantic projection drift detected at {phase}")
    return {
        "phase": phase,
        "expected_codex_home": expected_home,
        "actual_codex_home": actual_home,
        "expected_config_path": str(snapshot.config_path),
        "actual_config_path": str(snapshot.config_path),
        "expected_config_sha256": snapshot.snapshot_sha256,
        "actual_config_sha256": snapshot.snapshot_sha256,
        "config_size": snapshot.snapshot_size,
        "snapshot_path": str(snapshot.snapshot_path),
        "verified": True,
        "executable_path": str(executable.path),
        "executable_version": executable.version,
        "executable_sha256": executable.sha256,
        "executable_architecture": executable.architecture,
    }


def _require_external(path: Path, protected: list[Path], *, label: str) -> Path:
    resolved = path.resolve()
    for item in protected:
        base = item.resolve()
        if resolved == base or resolved.is_relative_to(base):
            raise SystemExit(f"{label} must live outside source repository {base}: {resolved}")
    return resolved


def _validate_repo(repo: Path, expected_commit: str) -> dict[str, Any]:
    repo = repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repository directory does not exist: {repo}")
    head = _run_git(repo, "rev-parse", "HEAD")
    if head != expected_commit:
        raise SystemExit(
            f"repository HEAD mismatch for {repo}: expected={expected_commit}, actual={head}"
        )
    status = _run_git(repo, "status", "--porcelain")
    if status:
        raise SystemExit(f"repository must be clean before execution: {repo}\n{status}")
    return {"path": str(repo), "head": head, "clean": True}


def _load_freeze_bundle(
    freeze_dir: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Any, dict[str, Any]]:
    freeze_dir = freeze_dir.resolve()
    expected_timeout = _validate_timeout_contract(contract)
    freeze_manifest_path = freeze_dir / "freeze-manifest.json"
    if not freeze_manifest_path.is_file():
        raise SystemExit(f"missing freeze-manifest.json in {freeze_dir}")
    freeze_manifest = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    if freeze_manifest.get("campaign_id") != contract["campaign_id"]:
        raise SystemExit("freeze manifest campaign_id does not match public campaign contract")
    if freeze_manifest.get("provider_execution_timeout_seconds") != expected_timeout:
        raise SystemExit("freeze manifest provider execution timeout does not match V15 contract")
    if freeze_manifest.get("provider_execution_started") is not False:
        raise SystemExit("V15 freeze manifest must precede provider execution")

    runtime_lock_path = freeze_dir / freeze_manifest["runtime_lock"]
    if not runtime_lock_path.is_file():
        raise SystemExit(f"runtime lock does not exist: {runtime_lock_path}")
    runtime_lock = json.loads(runtime_lock_path.read_text(encoding="utf-8"))
    if runtime_lock.get("schema_version") != "arc-empirical-runtime-lock-v15":
        raise SystemExit("unsupported V15 runtime-lock schema")
    provider_profile = contract["provider_profile"]
    runtime_expectations = {
        "launcher_type": contract["launcher"]["type"],
        "launcher_script_path": str(Path(contract["launcher"]["script_path"]).expanduser().resolve()),
        "python_executable_path": str(Path(contract["launcher"]["python_path"]).expanduser().resolve()),
        "python_version": contract["launcher"]["python_version"],
        "python_sha256": contract["launcher"]["python_sha256"],
        "python_architecture": contract["launcher"]["architecture"],
        "launcher_environment_root": str(Path(contract["launcher"]["environment_root"]).expanduser().resolve()),
        "provider": provider_profile["provider"],
        "model": provider_profile["model"],
        "role": provider_profile["role"],
        "capabilities": sorted(provider_profile["capabilities"]),
        "env_allow": sorted(provider_profile["env_allow"]),
        "effective_argv_sha256": provider_profile["effective_argv_sha256"],
        "provider_cli_version": contract["provider_runtime"]["version"],
        "codex_executable_path": contract["provider_runtime"]["codex_executable_path"],
        "codex_executable_version": contract["provider_runtime"]["codex_executable_version"],
        "codex_executable_sha256": contract["provider_runtime"]["codex_executable_sha256"],
        "codex_executable_architecture": contract["provider_runtime"]["codex_executable_architecture"],
        "codex_release_asset_sha256": contract["provider_runtime"]["codex_release_asset_sha256"],
        "provider_execution_timeout_seconds": int(
            contract["shared_protocol"]["provider_execution_timeout_seconds"]
        ),
        "auth_mode": contract["provider_runtime"]["auth_mode"],
        "codex_home": contract["provider_runtime"]["codex_home"],
        "codex_config_path": contract["provider_runtime"]["codex_config_path"],
        "codex_config_sha256": contract["provider_runtime"]["codex_config_sha256"],
        "codex_config_size": contract["provider_runtime"]["codex_config_size"],
        "codex_snapshot_path": contract["provider_runtime"]["codex_snapshot_path"],
        "codex_snapshot_sha256": contract["provider_runtime"]["codex_snapshot_sha256"],
        "codex_snapshot_manifest_path": contract["provider_runtime"]["codex_snapshot_manifest_path"],
        "codex_snapshot_manifest_sha256": contract["provider_runtime"]["codex_snapshot_manifest_sha256"],
        "codex_snapshot_codex_version": contract["provider_runtime"]["codex_snapshot_codex_version"],
        "codex_snapshot_provider": contract["provider_runtime"]["codex_snapshot_provider"],
        "codex_snapshot_authentication_required": contract["provider_runtime"]["codex_snapshot_authentication_required"],
        "codex_snapshot_semantic_projection": contract["provider_runtime"]["codex_snapshot_semantic_projection"],
    }
    runtime_mismatches = [
        key for key, expected in runtime_expectations.items() if runtime_lock.get(key) != expected
    ]
    if runtime_mismatches:
        raise SystemExit(
            "runtime lock does not match the V15 provider contract: " + ", ".join(runtime_mismatches)
        )
    if runtime_lock.get("lock_digest") != freeze_manifest.get("runtime_lock_digest"):
        raise SystemExit("freeze manifest runtime-lock digest does not match runtime-lock payload")

    meta_path = freeze_dir / freeze_manifest["meta_plan"]
    meta = load_meta_preregistration(meta_path)
    if meta.meta_id != contract["campaign_id"]:
        raise SystemExit("frozen meta-study ID does not match campaign contract")
    if meta.plan_digest != freeze_manifest.get("meta_plan_digest"):
        raise SystemExit("freeze manifest meta-plan digest does not match self-digesting meta plan")

    protocol = contract["shared_protocol"]
    if meta.bootstrap_samples != int(protocol["meta_bootstrap_samples"]):
        raise SystemExit("meta bootstrap-sample count drifted from public campaign contract")
    if abs(meta.ci - float(protocol["meta_ci"])) > 1e-12:
        raise SystemExit("meta CI drifted from public campaign contract")
    if meta.random_seed != int(protocol["meta_random_seed"]):
        raise SystemExit("meta random seed drifted from public campaign contract")

    expected_benchmarks = {
        contract["repositories"][slug]["benchmark_id"] for slug in REPOSITORY_ORDER
    }
    if {item.benchmark_id for item in meta.repositories} != expected_benchmarks:
        raise SystemExit("meta plan repository set does not match the public campaign contract")

    refs = {item.benchmark_id: item for item in meta.repositories}
    plans: dict[str, Any] = {}
    frozen_repositories = freeze_manifest.get("repository_plans", {})
    if set(frozen_repositories) != set(REPOSITORY_ORDER):
        raise SystemExit(
            "freeze manifest must contain exactly the three preregistered repositories"
        )

    for slug in REPOSITORY_ORDER:
        repo_contract = contract["repositories"][slug]
        frozen = frozen_repositories[slug]
        plan_path = freeze_dir / frozen["path"]
        plan = load_preregistration(plan_path)
        if plan.study_id != repo_contract["study_id"]:
            raise SystemExit(f"study_id drift detected for {slug}")
        if plan.benchmark_id != repo_contract["benchmark_id"]:
            raise SystemExit(f"benchmark_id drift detected for {slug}")
        if plan.canonical_repo_commit != repo_contract["commit"]:
            raise SystemExit(f"canonical repository commit drift detected for {slug}")
        if plan.plan_digest != frozen["plan_digest"]:
            raise SystemExit(f"freeze manifest plan digest mismatch for {slug}")
        if plan.runtime.hidden_tests_digest != frozen["hidden_tests_digest"]:
            raise SystemExit(f"freeze manifest hidden-test digest mismatch for {slug}")
        if plan.runtime.hidden_tests_digest != repo_contract["hidden_tree_sha256"]:
            raise SystemExit(f"public/private hidden-test contract drift detected for {slug}")
        if plan.runtime.provider_execution_timeout_seconds != int(
            protocol["provider_execution_timeout_seconds"]
        ):
            raise SystemExit(f"provider execution timeout drift detected for {slug}")
        if plan.runtime.visible_test_harness is None:
            raise SystemExit(f"visible test harness is missing for {slug}")
        if (
            plan.runtime.visible_test_harness.model_dump(mode="json")
            != repo_contract["visible_test_harness"]
        ):
            raise SystemExit(f"visible test harness drift detected for {slug}")
        if plan.runtime.verification_level != protocol["verification_level"]:
            raise SystemExit(f"verification-level drift detected for {slug}")
        if plan.design.repeats != int(protocol["repeats"]):
            raise SystemExit(f"repetition-count drift detected for {slug}")
        if plan.design.bootstrap_samples != int(protocol["bootstrap_samples"]):
            raise SystemExit(f"repository bootstrap-count drift detected for {slug}")
        if abs(plan.design.ci - float(protocol["ci"])) > 1e-12:
            raise SystemExit(f"repository CI drift detected for {slug}")
        ref = refs.get(plan.benchmark_id)
        if ref is None or ref.plan_digest != plan.plan_digest:
            raise SystemExit(f"meta plan does not freeze the exact repository plan for {slug}")
        plans[slug] = plan

    return freeze_manifest, runtime_lock, meta, plans


def _load_frozen_profiles(
    freeze_dir: Path,
    freeze_manifest: dict[str, Any],
    contract: dict[str, Any],
    plans: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    references = freeze_manifest.get("repository_profiles")
    if not isinstance(references, dict) or set(references) != set(REPOSITORY_ORDER):
        raise SystemExit("V15 freeze must contain exactly three frozen repository profiles")
    profiles: dict[str, dict[str, Any]] = {}
    expected_profiles = _frozen_profile_payloads(contract, plans)
    for repository in REPOSITORY_ORDER:
        reference = references[repository]
        path = freeze_dir / str(reference["path"])
        if not path.is_file():
            raise SystemExit(f"missing frozen V15 profile for {repository}: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload != expected_profiles[repository]:
            raise SystemExit(f"frozen V15 profile semantic drift for {repository}")
        if frozen_profile_digest(payload) != reference.get("profile_digest"):
            raise SystemExit(f"frozen V15 profile digest mismatch for {repository}")
        profiles[repository] = payload
    return profiles


def _study_dir(output_root: Path, plan: Any, attempt_id: str) -> Path:
    return output_root / plan.benchmark_id / "studies" / f"{plan.study_id}-{attempt_id}"


def _validate_live_repository(
    repo: Path,
    plan: Any,
    *,
    hidden_dir: Path,
    runtime_lock_path: Path,
    profile_path: Path,
    frozen_profile: dict[str, Any],
) -> dict[str, Any]:
    base_report = _validate_repo(repo, plan.canonical_repo_commit)
    actual_hidden_digest = tree_digest(hidden_dir)
    if actual_hidden_digest != plan.runtime.hidden_tests_digest:
        raise SystemExit(
            f"hidden-test tree drift for {plan.benchmark_id}: "
            f"planned={plan.runtime.hidden_tests_digest}, actual={actual_hidden_digest}"
        )

    try:
        config = load_staged_profile(
            profile_path,
            frozen_profile,
            repository=frozen_profile["repository"],
        )
    except ProfileStagingError as exc:
        raise SystemExit(f"PROFILE_STAGING_FAILED: {exc}") from exc
    profile = config.agents.get(plan.runtime.agent_profile)
    if profile is None:
        raise SystemExit(
            f"preregistered profile {plan.runtime.agent_profile!r} is not configured in {repo}"
        )
    invocation_config = profile_invocation_config(profile, require_complete=profile.provider == "codex")
    timeout_seconds = int(plan.runtime.provider_execution_timeout_seconds or 0)
    if config.provider_execution_timeout_seconds != timeout_seconds:
        raise SystemExit(
            f"provider execution timeout configuration drift for {repo}: "
            f"planned={timeout_seconds}, actual={config.provider_execution_timeout_seconds}"
        )
    verify_runtime_lock(
        repo,
        profile.name,
        runtime_lock_path,
        ARC_REPO_ROOT,
        provider_execution_timeout_seconds=timeout_seconds,
        profile_path=profile_path,
    )
    validate_execution_environment(
        plan,
        repo,
        provider=profile.provider,
        model=profile.model,
        profile_role=profile.role,
        profile_capabilities=profile.capabilities,
        visible_test_cmd=config.visible_test_cmd,
        visible_test_harness=config.visible_test_harness,
        hard_project_usd=config.hard_project_usd,
        hidden_test_dir=hidden_dir,
        verification_level=plan.runtime.verification_level,
        provider_execution_timeout_seconds=timeout_seconds,
        provider_codex_home=profile.codex_home,
        provider_codex_config_path=profile.codex_config_path,
        provider_codex_config_sha256=(
            plan.runtime.provider_codex_config_sha256
            if profile.codex_config_path
            else None
        ),
        provider_codex_snapshot_path=(str(invocation_config.snapshot_path) if invocation_config else None),
        provider_codex_snapshot_sha256=(invocation_config.snapshot_sha256 if invocation_config else None),
        provider_codex_snapshot_size=(invocation_config.snapshot_size if invocation_config else None),
        provider_codex_manifest_path=(
            str(invocation_config.manifest_path)
            if invocation_config and invocation_config.manifest_path
            else None
        ),
        provider_codex_manifest_sha256=(
            invocation_config.manifest_sha256 if invocation_config else None
        ),
        provider_codex_version=(invocation_config.codex_version if invocation_config else None),
        provider_codex_provider=(invocation_config.provider if invocation_config else None),
        provider_codex_authentication_required=(
            invocation_config.authentication_required if invocation_config else None
        ),
        provider_codex_semantic_projection=(
            dict(invocation_config.semantic_projection) if invocation_config else None
        ),
    )
    harness = config.visible_test_harness
    if not harness:
        raise SystemExit(f"repository-specific Docker harness is missing for {repo}")
    sandbox = SandboxRunner(
        repo,
        network_enabled=bool(harness.get("network_enabled", False)),
        timeout_seconds=int(harness.get("timeout_seconds", 120)),
        image=harness.get("image"),
        image_digest=harness.get("image_digest"),
        tmpfs_noexec=not bool(harness.get("tmpfs_exec", False)),
    )
    try:
        sandbox_report = sandbox.verify_available()
    except SandboxUnavailable as exc:
        sandbox_report = {
            "backend": harness.get("backend", "docker"),
            "image": harness.get("image"),
            "expected_image_digest": harness.get("image_digest"),
            "actual_image_digest": None,
            "ready": False,
            "error": str(exc),
        }
    return {
        **base_report,
        "hidden_tests_digest": actual_hidden_digest,
        "profile": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "provider_execution_timeout_seconds": timeout_seconds,
        "timeout_contract_verified": True,
        "visible_test_harness": config.visible_test_harness,
        "sandbox": sandbox_report,
    }


def _run_logged(args: list[str], *, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8") as log:
        log.write("command=" + json.dumps(args) + "\n")
        log.flush()
        proc = subprocess.Popen(
            args,
            cwd=ARC_REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
            log.flush()
        returncode = proc.wait()
    if returncode != 0:
        raise RuntimeError(f"command failed with exit code {returncode}; see {log_path.resolve()}")


def preflight_campaign(
    repos: dict[str, Path],
    *,
    hidden_root: Path,
    freeze_dir: Path,
    results_root: Path,
    workspace_root: Path,
    attempt_id: str,
) -> dict[str, Any]:
    _validate_attempt_id(attempt_id)
    contract = _load_contract()
    assert_source_repository_clean(ARC_REPO_ROOT, stage="static_preflight_start")
    launcher_identity = _validate_launcher_identity(contract, phase="static_preflight_start")
    # The immutable invocation identity arrives only through the attempt-scoped
    # staged profiles. Ambient repository-local ARC state is never consulted.
    expected_timeout = _validate_timeout_contract(contract)
    operational_policy = _validate_operational_policy(contract)
    freeze_manifest, runtime_lock, meta, plans = _load_freeze_bundle(freeze_dir, contract)

    resolved_repos = {slug: repos[slug].resolve() for slug in REPOSITORY_ORDER}
    protected = [ARC_REPO_ROOT.resolve(), *resolved_repos.values()]
    results_root = _require_external(results_root, protected, label="results-root")
    workspace_root = _require_external(workspace_root, protected, label="workspace-root")
    if results_root == workspace_root:
        raise SystemExit("results-root and workspace-root must be distinct directories")

    execution_root = results_root / contract["campaign_id"] / attempt_id
    execution_workspace = workspace_root / contract["campaign_id"] / attempt_id
    if execution_root.exists():
        raise SystemExit(
            f"campaign attempt already has result artifacts; choose a new attempt-id: {execution_root}"
        )
    if execution_workspace.exists():
        raise SystemExit(
            f"campaign attempt already has runtime workspace; clean it deliberately or choose a new attempt-id: {execution_workspace}"
        )

    runtime_lock_path = freeze_dir.resolve() / freeze_manifest["runtime_lock"]
    hidden_root = hidden_root.resolve()
    frozen_profiles = _load_frozen_profiles(
        freeze_dir,
        freeze_manifest,
        contract,
        plans,
    )
    try:
        staged_profiles = stage_frozen_repository_profiles(frozen_profiles, execution_workspace)
    except ProfileStagingError as exc:
        raise SystemExit(f"PROFILE_STAGING_FAILED: {exc}") from exc
    profile_report = {
        slug: {
            "path": str(staged_profiles[slug].path),
            "frozen_profile_digest": staged_profiles[slug].frozen_profile_digest,
            "staged_profile_digest": staged_profiles[slug].staged_profile_digest,
            "serialized_sha256": staged_profiles[slug].serialized_sha256,
            "semantic_parity": staged_profiles[slug].semantic_parity,
        }
        for slug in REPOSITORY_ORDER
    }
    assert_source_repository_clean(ARC_REPO_ROOT, stage="after_profile_staging")
    repository_report: dict[str, Any] = {}
    for slug in REPOSITORY_ORDER:
        plan = plans[slug]
        repo = resolved_repos[slug]
        live = _validate_live_repository(
            repo,
            plan,
            hidden_dir=hidden_root / slug,
            runtime_lock_path=runtime_lock_path,
            profile_path=staged_profiles[slug].path,
            frozen_profile=frozen_profiles[slug],
        )
        repo_output_root = execution_root / "repositories" / slug
        repo_workspace_root = execution_workspace / slug
        expected_study = _study_dir(repo_output_root, plan, attempt_id)
        if expected_study.exists():
            raise SystemExit(f"study output already exists for {slug}: {expected_study}")
        repository_report[slug] = {
            **live,
            "study_id": plan.study_id,
            "benchmark_id": plan.benchmark_id,
            "plan_digest": plan.plan_digest,
            "output_root": str(repo_output_root),
            "workspace_root": str(repo_workspace_root),
            "expected_study_dir": str(expected_study),
        }

    handoff = qualify_run_plan_handoff(
        resolved_repos["click"],
        hidden_root / "click",
        staged_profiles["click"].path,
    )
    assert_source_repository_clean(ARC_REPO_ROOT, stage="after_static_preflight")

    provider = contract["provider_profile"]["provider"]
    provider_environment = _provider_environment(contract)
    provider_identity = _validate_provider_runtime_identity(contract, phase="preflight")
    auth = auth_status(
        provider,
        environment=provider_environment,
        executable=contract["provider_runtime"]["codex_executable_path"],
    )
    sandbox_ready = all(
        repository.get("sandbox", {}).get("ready") is True
        for repository in repository_report.values()
    )
    timeout_contract_verified = all(
        plan.runtime.provider_execution_timeout_seconds == expected_timeout
        for plan in plans.values()
    )
    static_ready = bool(
        auth.installed
        and auth.authenticated
        and auth.auth_method == "ChatGPT / OpenAI OAuth"
        and sandbox_ready
        and timeout_contract_verified
        and handoff["provider_environment_contract_verified"]
        and handoff["run_plan_provider_environment_handoff_verified"]
    )
    return {
        "schema_version": "arc-campaign-preflight-v15",
        "checked_at_utc": _now(),
        "campaign_id": contract["campaign_id"],
        "attempt_id": attempt_id,
        "arc_commit": runtime_lock["arc_commit"],
        "arc_worktree_clean": runtime_lock.get("arc_worktree_clean") is True,
        "freeze_manifest_sha256": _sha256_file(freeze_dir.resolve() / "freeze-manifest.json"),
        "runtime_lock_digest": runtime_lock["lock_digest"],
        "provider_cli_version": runtime_lock["provider_cli_version"],
        "meta_plan_digest": meta.plan_digest,
        "provider_execution_timeout_seconds": expected_timeout,
        "codex_home": contract["provider_runtime"]["codex_home"],
        "codex_config_path": contract["provider_runtime"]["codex_config_path"],
        "codex_config_sha256": contract["provider_runtime"]["codex_config_sha256"],
        "provider_environment_expected": provider_environment,
        "provider_environment_actual": provider_environment,
        "provider_runtime_identity": provider_identity,
        "launcher_identity": launcher_identity,
        "provider_auth": {
            "provider": auth.provider,
            "installed": auth.installed,
            "authenticated": auth.authenticated,
            "state": auth.state,
            "detail": auth.detail,
            "auth_mode": "chatgpt_subscription" if auth.auth_method == "ChatGPT / OpenAI OAuth" else auth.auth_method,
        },
        "sandbox_identities_verified": sandbox_ready,
        "timeout_contract_verified": timeout_contract_verified,
        "provider_environment_contract_verified": handoff["provider_environment_contract_verified"],
        "run_plan_provider_environment_handoff_verified": handoff[
            "run_plan_provider_environment_handoff_verified"
        ],
        "run_plan_handoff_qualification": handoff,
        "static_preflight_ready": static_ready,
        "profile_staging": profile_report,
        "profile_staging_ready": all(
            item["semantic_parity"] for item in profile_report.values()
        ),
        "execution_boundary_ready": False,
        "ready_for_execution": False,
        "censor_retry_policy_verified": True,
        "checkpoint_policy_verified": operational_policy["ledger"] == "append_only_sqlite_atomic_task_state",
        "provider_requests": 0,
        "execution_root": str(execution_root),
        "workspace_root": str(execution_workspace),
        "repositories": repository_report,
    }


def execute_campaign(
    repos: dict[str, Path],
    *,
    hidden_root: Path,
    freeze_dir: Path,
    results_root: Path,
    workspace_root: Path,
    attempt_id: str,
) -> Path:
    report = preflight_campaign(
        repos,
        hidden_root=hidden_root,
        freeze_dir=freeze_dir,
        results_root=results_root,
        workspace_root=workspace_root,
        attempt_id=attempt_id,
    )
    if not (report["static_preflight_ready"] and report["profile_staging_ready"]):
        auth = report["provider_auth"]
        raise SystemExit(
            "provider authentication is not ready: "
            f"state={auth['state']}, detail={auth['detail']}. "
            "Authenticate with the vendor CLI before executing the frozen study."
        )

    contract = _load_contract()
    freeze_manifest, _, meta, plans = _load_freeze_bundle(freeze_dir, contract)
    execution_root = Path(report["execution_root"])
    execution_workspace = Path(report["workspace_root"])
    execution_root.mkdir(parents=True, exist_ok=False)
    logs_root = execution_root / "logs"
    frozen_profiles = _load_frozen_profiles(
        freeze_dir,
        freeze_manifest,
        contract,
        plans,
    )
    staged_profile_paths = {
        slug: Path(report["profile_staging"][slug]["path"])
        for slug in REPOSITORY_ORDER
    }

    ledger_path, manifest_path, checkpoint_path, pre_execution_manifest = (
        _initialize_execution_boundary(
            contract=contract,
            report=report,
            freeze_manifest=freeze_manifest,
            meta=meta,
            plans=plans,
            execution_root=execution_root,
            attempt_id=attempt_id,
        )
    )
    with ProductionLedger(
        ledger_path,
        campaign_id=contract["campaign_id"],
        attempt_id=attempt_id,
        expected_tasks=162,
        checkpoint_path=checkpoint_path,
    ) as production_ledger:
        boundary = production_ledger.execution_boundary_snapshot(
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
        )
    assert_source_repository_clean(ARC_REPO_ROOT, stage="after_execution_boundary_initialization")
    if not boundary["ready"]:
        raise SystemExit(
            "BLOCKED_PRE_EXECUTION: " + (boundary["blocking_reason"] or "boundary is not ready")
        )

    ledger: dict[str, Any] = {
        "schema_version": SCHEMA,
        "campaign_id": contract["campaign_id"],
        "attempt_id": attempt_id,
        "started_at_utc": _now(),
        "completed_at_utc": None,
        "status": "RUNNING",
        "provider_execution_started": False,
        "provider_execution_started_at_utc": None,
        "freeze_manifest_sha256": report["freeze_manifest_sha256"],
        "runtime_lock_digest": report["runtime_lock_digest"],
        "meta_plan_digest": meta.plan_digest,
        "arc_commit": report["arc_commit"],
        "provider_cli_version": report["provider_cli_version"],
        "provider_execution_timeout_seconds": report["provider_execution_timeout_seconds"],
        "provider_auth_state_at_start": report["provider_auth"]["state"],
        "preflight": report,
        "pre_execution_manifest": str(manifest_path),
        "production_ledger": str(ledger_path),
        "checkpoint": str(checkpoint_path),
        "execution_boundary": boundary,
        "repositories": {
            slug: {
                "status": "PENDING",
                "plan_digest": plans[slug].plan_digest,
                "live_revalidated_at_utc": None,
                "provider_auth_state_before_run": None,
                "started_at_utc": None,
                "completed_at_utc": None,
                "study_dir": None,
                "export_dir": None,
                "log": None,
                "error": None,
            }
            for slug in REPOSITORY_ORDER
        },
        "meta": {
            "status": "PENDING",
            "output_dir": None,
            "log": None,
            "error": None,
        },
        "retry_policy": (
            "No automatic retry or overwrite. Failed attempts remain immutable; any replacement "
            "requires a new explicit attempt ID and must be justified by the preregistered exclusions."
        ),
    }
    ledger_path = execution_root / "execution-manifest.json"
    _atomic_json(ledger_path, ledger)

    study_dirs: list[Path] = []
    runtime_lock_path = freeze_dir.resolve() / freeze_manifest["runtime_lock"]
    provider = contract["provider_profile"]["provider"]
    provider_environment = _provider_environment(contract)
    try:
        for slug in REPOSITORY_ORDER:
            plan = plans[slug]
            repo_state = ledger["repositories"][slug]

            repo_state["provider_runtime_before"] = _validate_provider_runtime_identity(
                contract, phase=f"before_{slug}"
            )

            # Revalidate immediately before each expensive repository study. A long
            # campaign must not assume the machine remained unchanged since the
            # campaign-level preflight.
            _validate_live_repository(
                repos[slug].resolve(),
                plan,
                hidden_dir=hidden_root.resolve() / slug,
                runtime_lock_path=runtime_lock_path,
                profile_path=staged_profile_paths[slug],
                frozen_profile=frozen_profiles[slug],
            )
            auth = auth_status(
                provider,
                environment=provider_environment,
                executable=contract["provider_runtime"]["codex_executable_path"],
            )
            repo_state["live_revalidated_at_utc"] = _now()
            repo_state["provider_auth_state_before_run"] = auth.state
            if not (auth.installed and auth.authenticated):
                raise RuntimeError(
                    f"provider authentication drift before {slug}: state={auth.state}, detail={auth.detail}"
                )

            repo_state["status"] = "RUNNING"
            repo_state["started_at_utc"] = _now()
            log_path = logs_root / f"{slug}-run-plan.log"
            repo_state["log"] = str(log_path)
            if not ledger["provider_execution_started"]:
                ledger["provider_execution_started"] = True
                ledger["provider_execution_started_at_utc"] = _now()
            _atomic_json(ledger_path, ledger)
            assert_source_repository_clean(ARC_REPO_ROOT, stage=f"before_provider_boundary_{slug}")

            repo_output_root = execution_root / "repositories" / slug
            repo_workspace_root = execution_workspace / slug
            plan_path = freeze_dir.resolve() / freeze_manifest["repository_plans"][slug]["path"]
            hidden_dir = hidden_root.resolve() / slug
            command = [
                sys.executable,
                "-m",
                "cli.bootstrap",
                "benchmark",
                "run-plan",
                str(plan_path),
                "--repo",
                str(repos[slug].resolve()),
                "--attempt-id",
                attempt_id,
                "--output-root",
                str(repo_output_root),
                "--workspace-root",
                str(repo_workspace_root),
                "--hidden-test-dir",
                str(hidden_dir),
                "--production-ledger",
                str(ledger_path),
                "--production-manifest",
                str(manifest_path),
                "--production-checkpoint",
                str(checkpoint_path),
                "--production-campaign-id",
                contract["campaign_id"],
                "--production-attempt-id",
                attempt_id,
                "--production-repository",
                slug,
                "--production-profile",
                str(staged_profile_paths[slug]),
            ]
            _run_logged(command, log_path=log_path)
            assert_source_repository_clean(ARC_REPO_ROOT, stage=f"after_provider_boundary_{slug}")
            repo_state["provider_runtime_after"] = _validate_provider_runtime_identity(
                contract, phase=f"after_{slug}"
            )

            study_dir = _study_dir(repo_output_root, plan, attempt_id)
            if not (study_dir / "study.json").is_file():
                raise RuntimeError(f"completed CLI run did not emit study.json for {slug}")
            provenance = json.loads((study_dir / "provenance.json").read_text(encoding="utf-8"))
            if provenance.get("extra", {}).get("plan_digest") != plan.plan_digest:
                raise RuntimeError(f"completed study provenance plan digest mismatch for {slug}")

            export_dir = study_dir / "exports"
            export_log = logs_root / f"{slug}-export.log"
            _run_logged(
                [
                    sys.executable,
                    "-m",
                    "cli.bootstrap",
                    "benchmark",
                    "export",
                    str(study_dir),
                    "--output-dir",
                    str(export_dir),
                ],
                log_path=export_log,
            )
            assert_source_repository_clean(ARC_REPO_ROOT, stage=f"after_measurement_export_{slug}")
            if not (export_dir / "export_manifest.json").is_file():
                raise RuntimeError(f"study export did not emit export_manifest.json for {slug}")

            repo_state["status"] = "SUCCEEDED"
            repo_state["completed_at_utc"] = _now()
            repo_state["study_dir"] = str(study_dir)
            repo_state["export_dir"] = str(export_dir)
            study_dirs.append(study_dir)
            _atomic_json(ledger_path, ledger)

        meta_state = ledger["meta"]
        meta_state["status"] = "RUNNING"
        meta_output = execution_root / "meta"
        meta_log = logs_root / "meta.log"
        meta_state["output_dir"] = str(meta_output)
        meta_state["log"] = str(meta_log)
        _atomic_json(ledger_path, ledger)
        meta_plan_path = freeze_dir.resolve() / freeze_manifest["meta_plan"]
        _run_logged(
            [
                sys.executable,
                "-m",
                "cli.bootstrap",
                "benchmark",
                "meta",
                str(meta_plan_path),
                *(str(path) for path in study_dirs),
                "--output-dir",
                str(meta_output),
            ],
            log_path=meta_log,
        )
        assert_source_repository_clean(ARC_REPO_ROOT, stage="after_meta_measurement_export")
        if not (meta_output / "meta_study.json").is_file():
            raise RuntimeError("meta-analysis completed without meta_study.json")
        meta_state["status"] = "SUCCEEDED"

        ledger["status"] = "SUCCEEDED"
        ledger["completed_at_utc"] = _now()
        _atomic_json(ledger_path, ledger)
        print(f"campaign_execution={execution_root.resolve()}")
        print(f"execution_manifest={ledger_path.resolve()}")
        print(f"meta_artifacts={meta_output.resolve()}")
        return execution_root
    except BaseException as exc:
        for slug in REPOSITORY_ORDER:
            state = ledger["repositories"][slug]
            if state["status"] == "RUNNING":
                state["status"] = "FAILED"
                state["completed_at_utc"] = _now()
                state["error"] = str(exc)
                break
        if ledger["meta"]["status"] == "RUNNING":
            ledger["meta"]["status"] = "FAILED"
            ledger["meta"]["error"] = str(exc)
        ledger["status"] = "FAILED"
        ledger["completed_at_utc"] = _now()
        ledger["error"] = str(exc)
        _atomic_json(ledger_path, ledger)
        raise


def execution_boundary_dry_run(
    repos: dict[str, Path],
    *,
    hidden_root: Path,
    freeze_dir: Path,
    results_root: Path,
    workspace_root: Path,
    attempt_id: str,
) -> dict[str, Any]:
    """Run the real V15 staging and ledger boundary without provider execution."""
    report = preflight_campaign(
        repos,
        hidden_root=hidden_root,
        freeze_dir=freeze_dir,
        results_root=results_root,
        workspace_root=workspace_root,
        attempt_id=attempt_id,
    )
    if not (report["static_preflight_ready"] and report["profile_staging_ready"]):
        report["ready_for_execution"] = False
        return report
    contract = _load_contract()
    freeze_manifest, _, meta, plans = _load_freeze_bundle(freeze_dir, contract)
    execution_root = Path(report["execution_root"])
    execution_root.mkdir(parents=True, exist_ok=False)
    ledger_path, manifest_path, checkpoint_path, _ = _initialize_execution_boundary(
        contract=contract,
        report=report,
        freeze_manifest=freeze_manifest,
        meta=meta,
        plans=plans,
        execution_root=execution_root,
        attempt_id=attempt_id,
    )
    with ProductionLedger(
        ledger_path,
        campaign_id=contract["campaign_id"],
        attempt_id=attempt_id,
        expected_tasks=162,
        checkpoint_path=checkpoint_path,
    ) as ledger:
        boundary = ledger.execution_boundary_snapshot(
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
        )
        counts = ledger.counts()
        checkpoint = ledger.checkpoint()
    assert_source_repository_clean(ARC_REPO_ROOT, stage="after_execution_boundary_dry_run")
    report.update(
        {
            "execution_boundary": boundary,
            "execution_boundary_ready": bool(boundary["ready"]),
            "provider_requests": 0,
            "logical_tasks": sum(counts.values()),
            "execution_instances": 0,
            "state_counts": counts,
            "checkpoint": checkpoint,
            "pre_execution_manifest": str(manifest_path),
            "production_ledger": str(ledger_path),
            "ready_for_execution": bool(
                report["static_preflight_ready"]
                and report["profile_staging_ready"]
                and boundary["ready"]
            ),
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--click-repo", type=Path, required=True)
    parser.add_argument("--httpx-repo", type=Path, required=True)
    parser.add_argument("--python-dotenv-repo", type=Path, required=True)
    parser.add_argument("--hidden-root", type=Path, required=True)
    parser.add_argument("--freeze-dir", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--attempt-id", default="a001")
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Start authenticated provider inference after a successful preflight. "
            "Without this flag the command is read-only."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run exact profile staging and execution-boundary initialization without a provider",
    )
    args = parser.parse_args()
    repos = {
        "click": args.click_repo,
        "httpx": args.httpx_repo,
        "python-dotenv": args.python_dotenv_repo,
    }
    if args.execute:
        execute_campaign(
            repos,
            hidden_root=args.hidden_root,
            freeze_dir=args.freeze_dir,
            results_root=args.results_root,
            workspace_root=args.workspace_root,
            attempt_id=args.attempt_id,
        )
        return

    if args.dry_run:
        report = execution_boundary_dry_run(
            repos,
            hidden_root=args.hidden_root,
            freeze_dir=args.freeze_dir,
            results_root=args.results_root,
            workspace_root=args.workspace_root,
            attempt_id=args.attempt_id,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        if not report["ready_for_execution"]:
            raise SystemExit(2)
        return

    report = preflight_campaign(
        repos,
        hidden_root=args.hidden_root,
        freeze_dir=args.freeze_dir,
        results_root=args.results_root,
        workspace_root=args.workspace_root,
        attempt_id=args.attempt_id,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ready_for_execution"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
