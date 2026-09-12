"""Pre-registered provider study plans for ARC benchmark execution."""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, Field, model_validator

from eval.comparison import validate_comparable_manifests
from eval.models import BenchmarkManifest


PRIMARY_METRICS = (
    "resolved_rate",
    "mean_context_tokens",
    "mean_provider_tokens",
    "mean_cost_usd",
    "p95_end_to_end_latency_ms",
    "stale_delivery_rate",
)


class StudyDesign(BaseModel):
    repeats: int = Field(default=6, ge=2)
    bootstrap_samples: int = Field(default=2000, ge=1)
    ci: float = Field(default=0.95, gt=0.0, lt=1.0)
    order_schedule: str = "balanced_crossover_v1"
    analysis_unit: str = "paired_repetition"
    primary_metrics: list[str] = Field(default_factory=lambda: list(PRIMARY_METRICS))
    exclusions: list[str] = Field(default_factory=list)


class StudyRuntimeContract(BaseModel):
    agent_profile: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str | None = None
    profile_role: str = ""
    profile_capabilities: list[str] = Field(default_factory=list)
    visible_test_cmd: list[str] = Field(default_factory=list)
    hard_project_usd: float = Field(ge=0.0)
    verification_level: str = "V0"
    hidden_tests_required: bool = False
    hidden_tests_digest: str | None = None

    @model_validator(mode="after")
    def hidden_test_contract(self) -> "StudyRuntimeContract":
        if self.hidden_tests_required and not self.hidden_tests_digest:
            raise ValueError("hidden_tests_required requires hidden_tests_digest")
        if not self.hidden_tests_required and self.hidden_tests_digest is not None:
            raise ValueError("hidden_tests_digest requires hidden_tests_required=true")
        return self


class PreregisteredStudy(BaseModel):
    schema_version: str = "arc-preregistered-study-v1"
    study_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    created_at_utc: str
    canonical_repo_commit: str = Field(
        min_length=40, max_length=40, pattern=r"^[0-9a-fA-F]{40}$"
    )
    manifests: list[BenchmarkManifest] = Field(min_length=2)
    design: StudyDesign
    runtime: StudyRuntimeContract
    planned_comparisons: list[str] = Field(default_factory=list)
    plan_digest: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> "PreregisteredStudy":
        if self.schema_version != "arc-preregistered-study-v1":
            raise ValueError(f"unsupported preregistration schema: {self.schema_version}")
        benchmark_ids = {manifest.benchmark_id for manifest in self.manifests}
        if benchmark_ids != {self.benchmark_id}:
            raise ValueError("embedded manifests must share preregistration benchmark_id")
        baselines = [manifest.baseline for manifest in self.manifests]
        if len(set(baselines)) != len(baselines):
            raise ValueError("embedded manifests must use unique baseline IDs")
        first = self.manifests[0]
        for other in self.manifests[1:]:
            validate_comparable_manifests(first, other)
        expected_pairs = {
            f"{left}-{right}"
            for left, right in itertools.combinations(sorted(baselines), 2)
        }
        if set(self.planned_comparisons) != expected_pairs:
            raise ValueError("planned_comparisons must enumerate every baseline pair exactly once")
        if self.design.order_schedule != "balanced_crossover_v1":
            raise ValueError("v1 preregistration requires balanced_crossover_v1")
        if self.design.analysis_unit != "paired_repetition":
            raise ValueError("v1 preregistration requires paired_repetition analysis unit")
        return self


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_plan_digest(plan: PreregisteredStudy | dict[str, Any]) -> str:
    if isinstance(plan, PreregisteredStudy):
        payload = plan.model_dump(mode="json")
    else:
        payload = dict(plan)
    payload["plan_digest"] = ""
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def tree_digest(path: str | Path) -> str:
    """Hash relative paths and bytes for an external hidden-test tree."""
    root = Path(path).resolve()
    if not root.is_dir():
        raise ValueError(f"hidden-test directory does not exist: {root}")
    files = sorted(item for item in root.rglob("*") if item.is_file())
    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = item.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _resolve_commit(repo: Path, ref: str) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", f"{ref}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git rev-parse failed").strip()
        raise ValueError(f"cannot resolve preregistered repository commit {ref!r}: {detail}")
    return proc.stdout.strip()


def create_preregistration(
    manifests: Sequence[BenchmarkManifest],
    source_repo: str | Path,
    *,
    study_id: str,
    provider: str,
    profile_role: str = "",
    profile_capabilities: Sequence[str] = (),
    visible_test_cmd: Sequence[str] = (),
    hard_project_usd: float,
    hidden_test_dir: str | Path | None = None,
    verification_level: str = "V0",
    repeats: int = 6,
    bootstrap_samples: int = 2000,
    ci: float = 0.95,
    exclusions: Sequence[str] = (),
    created_at_utc: str | None = None,
) -> PreregisteredStudy:
    manifest_list = [manifest.model_copy(deep=True) for manifest in manifests]
    if len(manifest_list) < 2:
        raise ValueError("preregistration requires at least two baseline manifests")
    first = manifest_list[0]
    for other in manifest_list[1:]:
        validate_comparable_manifests(first, other)
    if len({manifest.benchmark_id for manifest in manifest_list}) != 1:
        raise ValueError("preregistered manifests must share one benchmark_id")
    if len({manifest.agent_profile for manifest in manifest_list}) != 1:
        raise ValueError("preregistered manifests must share one agent_profile")
    if len({manifest.model for manifest in manifest_list}) != 1:
        raise ValueError("preregistered manifests must share one model")
    if len({manifest.baseline for manifest in manifest_list}) != len(manifest_list):
        raise ValueError("preregistered manifests must use unique baselines")

    repo = Path(source_repo).resolve()
    canonical_commit = _resolve_commit(repo, first.repo_commit)
    for manifest in manifest_list[1:]:
        if _resolve_commit(repo, manifest.repo_commit) != canonical_commit:
            raise ValueError("preregistered manifests do not resolve to one canonical commit")

    hidden_digest = tree_digest(hidden_test_dir) if hidden_test_dir is not None else None
    baselines = sorted(manifest.baseline for manifest in manifest_list)
    comparisons = [f"{left}-{right}" for left, right in itertools.combinations(baselines, 2)]
    plan = PreregisteredStudy(
        study_id=study_id,
        benchmark_id=first.benchmark_id,
        created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat(),
        canonical_repo_commit=canonical_commit,
        manifests=manifest_list,
        design=StudyDesign(
            repeats=repeats,
            bootstrap_samples=bootstrap_samples,
            ci=ci,
            exclusions=list(exclusions),
        ),
        runtime=StudyRuntimeContract(
            agent_profile=first.agent_profile,
            provider=provider,
            model=first.model,
            profile_role=profile_role,
            profile_capabilities=sorted(set(profile_capabilities)),
            visible_test_cmd=list(visible_test_cmd),
            hard_project_usd=float(hard_project_usd),
            verification_level=verification_level,
            hidden_tests_required=hidden_digest is not None,
            hidden_tests_digest=hidden_digest,
        ),
        planned_comparisons=comparisons,
    )
    return plan.model_copy(update={"plan_digest": compute_plan_digest(plan)})


def save_preregistration(path: str | Path, plan: PreregisteredStudy) -> Path:
    if plan.plan_digest != compute_plan_digest(plan):
        raise ValueError("refusing to save preregistration with invalid plan_digest")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_preregistration(path: str | Path) -> PreregisteredStudy:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    plan = PreregisteredStudy.model_validate(payload)
    actual = compute_plan_digest(plan)
    if plan.plan_digest != actual:
        raise ValueError(
            f"preregistration digest mismatch: recorded={plan.plan_digest}, actual={actual}"
        )
    return plan


def validate_execution_environment(
    plan: PreregisteredStudy,
    source_repo: str | Path,
    *,
    provider: str,
    model: str | None,
    profile_role: str,
    profile_capabilities: Sequence[str],
    visible_test_cmd: Sequence[str],
    hard_project_usd: float,
    hidden_test_dir: str | Path | None,
    verification_level: str = "V0",
) -> None:
    """Fail closed when the live execution contract differs from preregistration."""
    if plan.plan_digest != compute_plan_digest(plan):
        raise ValueError("preregistration plan_digest is invalid")

    repo = Path(source_repo).resolve()
    for manifest in plan.manifests:
        resolved = _resolve_commit(repo, manifest.repo_commit)
        if resolved != plan.canonical_repo_commit:
            raise ValueError(
                f"repository base drift for {manifest.baseline}: "
                f"planned={plan.canonical_repo_commit}, actual={resolved}"
            )

    live_hidden = tree_digest(hidden_test_dir) if hidden_test_dir is not None else None
    actual = {
        "provider": provider,
        "model": model,
        "profile_role": profile_role,
        "profile_capabilities": sorted(set(profile_capabilities)),
        "visible_test_cmd": list(visible_test_cmd),
        "hard_project_usd": float(hard_project_usd),
        "verification_level": verification_level,
        "hidden_tests_required": live_hidden is not None,
        "hidden_tests_digest": live_hidden,
    }
    expected = plan.runtime.model_dump(mode="json")
    expected.pop("agent_profile", None)
    mismatches = [
        key for key in sorted(expected)
        if expected[key] != actual.get(key)
    ]
    if mismatches:
        details = ", ".join(
            f"{key}: planned={expected[key]!r}, actual={actual.get(key)!r}"
            for key in mismatches
        )
        raise ValueError("execution environment differs from preregistration: " + details)
