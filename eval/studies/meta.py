"""Cross-repository preregistration and hierarchical meta-study aggregation."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

import numpy as np
from pydantic import BaseModel, Field, model_validator

from eval.studies.preregistration import (
    PRIMARY_METRICS,
    PreregisteredStudy,
    load_preregistration,
)


class RepositoryPlanRef(BaseModel):
    study_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    plan_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(min_length=1)
    model: str | None = None
    agent_profile: str = Field(min_length=1)
    baselines: list[str] = Field(min_length=2)
    context_token_budget: int = Field(ge=1)
    hard_task_usd: float
    hard_project_usd: float
    verification_level: str
    repeats: int = Field(ge=2)


class MetaStudyPlan(BaseModel):
    schema_version: str = "arc-meta-study-v1"
    meta_id: str = Field(min_length=1)
    created_at_utc: str
    repositories: list[RepositoryPlanRef] = Field(min_length=2)
    bootstrap_samples: int = Field(default=5000, ge=1)
    ci: float = Field(default=0.95, gt=0.0, lt=1.0)
    random_seed: int = 42
    analysis_unit: str = "repository_cluster"
    primary_metrics: list[str] = Field(default_factory=lambda: list(PRIMARY_METRICS))
    plan_digest: str = ""

    @model_validator(mode="after")
    def validate_contract(self) -> "MetaStudyPlan":
        if self.schema_version != "arc-meta-study-v1":
            raise ValueError(f"unsupported meta-study schema: {self.schema_version}")
        if self.analysis_unit != "repository_cluster":
            raise ValueError("v1 meta-study requires repository_cluster analysis unit")
        digests = [item.plan_digest for item in self.repositories]
        if len(digests) != len(set(digests)):
            raise ValueError("meta-study contains duplicate repository plan digests")
        benchmark_ids = [item.benchmark_id for item in self.repositories]
        if len(benchmark_ids) != len(set(benchmark_ids)):
            raise ValueError("meta-study requires unique benchmark_id values per repository")
        first = self.repositories[0]
        shared_fields = (
            "provider",
            "model",
            "agent_profile",
            "baselines",
            "context_token_budget",
            "hard_task_usd",
            "hard_project_usd",
            "verification_level",
            "repeats",
        )
        for other in self.repositories[1:]:
            for field in shared_fields:
                if getattr(other, field) != getattr(first, field):
                    raise ValueError(
                        f"repository study protocol differs on {field}: "
                        f"{first.benchmark_id} vs {other.benchmark_id}"
                    )
        return self


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_meta_plan_digest(plan: MetaStudyPlan | dict[str, Any]) -> str:
    payload = plan.model_dump(mode="json") if isinstance(plan, MetaStudyPlan) else dict(plan)
    payload["plan_digest"] = ""
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _repo_ref(plan: PreregisteredStudy) -> RepositoryPlanRef:
    first = plan.manifests[0]
    hard_task_values = {manifest.hard_task_usd for manifest in plan.manifests}
    context_values = {manifest.context_token_budget for manifest in plan.manifests}
    if len(hard_task_values) != 1 or None in hard_task_values:
        raise ValueError(f"study {plan.study_id} lacks one explicit hard_task_usd")
    if len(context_values) != 1:
        raise ValueError(f"study {plan.study_id} mixes context_token_budget values")
    return RepositoryPlanRef(
        study_id=plan.study_id,
        benchmark_id=plan.benchmark_id,
        plan_digest=plan.plan_digest,
        provider=plan.runtime.provider,
        model=plan.runtime.model,
        agent_profile=plan.runtime.agent_profile,
        baselines=sorted(manifest.baseline for manifest in plan.manifests),
        context_token_budget=next(iter(context_values)),
        hard_task_usd=float(next(iter(hard_task_values))),
        hard_project_usd=float(plan.runtime.hard_project_usd),
        verification_level=plan.runtime.verification_level,
        repeats=plan.design.repeats,
    )


def create_meta_preregistration(
    study_plans: Sequence[PreregisteredStudy],
    *,
    meta_id: str,
    bootstrap_samples: int = 5000,
    ci: float = 0.95,
    random_seed: int = 42,
    created_at_utc: str | None = None,
) -> MetaStudyPlan:
    plans = list(study_plans)
    if len(plans) < 2:
        raise ValueError("meta-study preregistration requires at least two repository plans")
    refs = [_repo_ref(plan) for plan in plans]
    meta = MetaStudyPlan(
        meta_id=meta_id,
        created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat(),
        repositories=refs,
        bootstrap_samples=bootstrap_samples,
        ci=ci,
        random_seed=random_seed,
    )
    return meta.model_copy(update={"plan_digest": compute_meta_plan_digest(meta)})


def save_meta_preregistration(path: str | Path, plan: MetaStudyPlan) -> Path:
    target = Path(path)
    if target.exists():
        raise ValueError(f"meta preregistration output already exists: {target}")
    if plan.plan_digest != compute_meta_plan_digest(plan):
        raise ValueError("meta-study plan digest does not match payload")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_meta_preregistration(path: str | Path) -> MetaStudyPlan:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"meta-study plan does not exist: {source}")
    plan = MetaStudyPlan.model_validate_json(source.read_text(encoding="utf-8"))
    expected = compute_meta_plan_digest(plan)
    if plan.plan_digest != expected:
        raise ValueError("meta-study plan digest mismatch; plan was modified")
    return plan


@dataclass(frozen=True)
class RepositoryStudyData:
    study_id: str
    benchmark_id: str
    plan_digest: str
    provider: str | None
    model: str | None
    agent_profile: str
    baselines: tuple[str, ...]
    deltas: dict[tuple[str, str, str], tuple[float, ...]]
    artifact_dir: Path


@dataclass(frozen=True)
class HierarchicalMetric:
    repository_count: int
    repetition_count: int
    mean_delta: float | None
    median_repository_delta: float | None
    ci_lower: float | None
    ci_upper: float | None


@dataclass(frozen=True)
class MetaPairedComparison:
    baseline_a: str
    baseline_b: str
    repository_wins_a: int
    repository_wins_b: int
    repository_ties: int
    metrics: dict[str, HierarchicalMetric]


@dataclass(frozen=True)
class MetaStudyResult:
    meta_id: str
    plan_digest: str
    repository_count: int
    studies: tuple[RepositoryStudyData, ...]
    comparisons: tuple[MetaPairedComparison, ...]
    artifact_dir: Path


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"required study artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _study_deltas(study_dir: str | Path) -> RepositoryStudyData:
    root = Path(study_dir).resolve()
    if (root / "failure.json").exists():
        raise ValueError(f"failed study cannot enter meta-analysis: {root}")
    study = _read_json(root / "study.json")
    provenance = _read_json(root / "provenance.json")
    extra = provenance.get("extra", {})
    if extra.get("preregistered") is not True:
        raise ValueError(f"meta-analysis requires preregistered study artifacts: {root}")
    plan_digest = str(extra.get("plan_digest") or "")
    if len(plan_digest) != 64:
        raise ValueError(f"study is missing preregistered plan_digest: {root}")

    repetitions = study.get("repetitions")
    if not isinstance(repetitions, list) or not repetitions:
        raise ValueError(f"study has no repetitions: {root}")

    deltas: dict[tuple[str, str, str], list[float]] = {}
    baseline_set: tuple[str, ...] | None = None
    for repeat in repetitions:
        repeat_root = root / str(repeat["artifact_dir"])
        paired = _read_json(repeat_root / "paired_run.json")
        baseline_meta = paired.get("baselines", {})
        labels = tuple(sorted(baseline_meta))
        if baseline_set is None:
            baseline_set = labels
        elif labels != baseline_set:
            raise ValueError(f"study mixes baseline sets across repetitions: {root}")
        summaries: dict[str, dict[str, Any]] = {}
        for baseline, metadata in baseline_meta.items():
            baseline_dir = repeat_root / str(metadata["artifact_dir"])
            summaries[baseline] = _read_json(baseline_dir / "summary.json")
        for left_index in range(len(labels)):
            for right_index in range(left_index + 1, len(labels)):
                left = labels[left_index]
                right = labels[right_index]
                for field in PRIMARY_METRICS:
                    left_value = summaries[left].get(field)
                    right_value = summaries[right].get(field)
                    if left_value is None or right_value is None:
                        continue
                    deltas.setdefault((left, right, field), []).append(
                        float(left_value) - float(right_value)
                    )

    return RepositoryStudyData(
        study_id=str(study["study_id"]),
        benchmark_id=str(study["benchmark_id"]),
        plan_digest=plan_digest,
        provider=extra.get("provider"),
        model=provenance.get("declared_model"),
        agent_profile=str(provenance.get("agent_profile") or ""),
        baselines=baseline_set or (),
        deltas={key: tuple(values) for key, values in deltas.items()},
        artifact_dir=root,
    )


def validate_meta_inputs(
    plan: MetaStudyPlan,
    study_dirs: Sequence[str | Path],
) -> tuple[RepositoryStudyData, ...]:
    studies = tuple(_study_deltas(path) for path in study_dirs)
    if len(studies) != len(plan.repositories):
        raise ValueError(
            f"meta-study expected {len(plan.repositories)} repositories, got {len(studies)}"
        )
    expected = {item.plan_digest: item for item in plan.repositories}
    actual: dict[str, RepositoryStudyData] = {}
    for study in studies:
        if study.plan_digest in actual:
            raise ValueError(f"duplicate completed study plan_digest: {study.plan_digest}")
        actual[study.plan_digest] = study
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise ValueError(
            f"completed studies do not match frozen meta-plan; missing={missing}, extra={extra}"
        )

    ordered: list[RepositoryStudyData] = []
    for ref in plan.repositories:
        study = actual[ref.plan_digest]
        if study.benchmark_id != ref.benchmark_id:
            raise ValueError(f"benchmark_id mismatch for plan {ref.plan_digest}")
        if study.provider != ref.provider:
            raise ValueError(f"provider mismatch for {ref.benchmark_id}")
        if study.model != ref.model:
            raise ValueError(f"model mismatch for {ref.benchmark_id}")
        if study.agent_profile != ref.agent_profile:
            raise ValueError(f"agent_profile mismatch for {ref.benchmark_id}")
        if list(study.baselines) != ref.baselines:
            raise ValueError(f"baseline set mismatch for {ref.benchmark_id}")
        ordered.append(study)
    return tuple(ordered)


def _hierarchical_metric(
    repo_vectors: Sequence[tuple[float, ...]],
    *,
    n_bootstraps: int,
    ci: float,
    random_seed: int,
) -> HierarchicalMetric:
    vectors = [tuple(values) for values in repo_vectors if values]
    if not vectors:
        return HierarchicalMetric(0, 0, None, None, None, None)
    repo_means = [mean(values) for values in vectors]
    point = float(mean(repo_means))
    med = float(median(repo_means))
    if len(vectors) == 1:
        return HierarchicalMetric(1, len(vectors[0]), point, med, point, point)
    rng = np.random.default_rng(random_seed & 0xFFFFFFFF)
    samples = np.empty(n_bootstraps, dtype=np.float64)
    repo_count = len(vectors)
    for index in range(n_bootstraps):
        selected = rng.integers(0, repo_count, size=repo_count)
        selected_means: list[float] = []
        for repo_index in selected:
            values = vectors[int(repo_index)]
            inner = rng.choice(
                np.asarray(values, dtype=np.float64),
                size=len(values),
                replace=True,
            )
            selected_means.append(float(np.mean(inner)))
        samples[index] = float(np.mean(selected_means))
    alpha = (1.0 - ci) / 2.0
    return HierarchicalMetric(
        repository_count=repo_count,
        repetition_count=sum(len(values) for values in vectors),
        mean_delta=point,
        median_repository_delta=med,
        ci_lower=float(np.percentile(samples, 100.0 * alpha)),
        ci_upper=float(np.percentile(samples, 100.0 * (1.0 - alpha))),
    )


def aggregate_meta_study(
    plan: MetaStudyPlan,
    study_dirs: Sequence[str | Path],
    *,
    output_dir: str | Path,
) -> MetaStudyResult:
    if plan.plan_digest != compute_meta_plan_digest(plan):
        raise ValueError("meta-study plan digest mismatch")
    studies = validate_meta_inputs(plan, study_dirs)
    target = Path(output_dir).resolve()
    if target.exists():
        raise ValueError(f"meta-study output already exists: {target}")
    target.mkdir(parents=True, exist_ok=False)

    baselines = tuple(plan.repositories[0].baselines)
    comparisons: list[MetaPairedComparison] = []
    repository_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    pair_index = 0
    for left_index in range(len(baselines)):
        for right_index in range(left_index + 1, len(baselines)):
            left = baselines[left_index]
            right = baselines[right_index]
            resolved_repo_means: list[float] = []
            metrics: dict[str, HierarchicalMetric] = {}
            for metric_index, metric in enumerate(plan.primary_metrics):
                vectors = [study.deltas.get((left, right, metric), ()) for study in studies]
                summary = _hierarchical_metric(
                    vectors,
                    n_bootstraps=plan.bootstrap_samples,
                    ci=plan.ci,
                    random_seed=plan.random_seed + pair_index * 100 + metric_index,
                )
                metrics[metric] = summary
                for study, values in zip(studies, vectors):
                    if not values:
                        continue
                    repo_mean = float(mean(values))
                    repository_rows.append(
                        {
                            "meta_id": plan.meta_id,
                            "benchmark_id": study.benchmark_id,
                            "study_id": study.study_id,
                            "plan_digest": study.plan_digest,
                            "baseline_a": left,
                            "baseline_b": right,
                            "metric": metric,
                            "repetitions": len(values),
                            "repository_mean_delta": repo_mean,
                        }
                    )
                    if metric == "resolved_rate":
                        resolved_repo_means.append(repo_mean)
                metric_rows.append(
                    {
                        "meta_id": plan.meta_id,
                        "baseline_a": left,
                        "baseline_b": right,
                        "metric": metric,
                        **asdict(summary),
                    }
                )
            wins_a = sum(value > 0.0 for value in resolved_repo_means)
            wins_b = sum(value < 0.0 for value in resolved_repo_means)
            ties = len(resolved_repo_means) - wins_a - wins_b
            comparisons.append(
                MetaPairedComparison(
                    baseline_a=left,
                    baseline_b=right,
                    repository_wins_a=wins_a,
                    repository_wins_b=wins_b,
                    repository_ties=ties,
                    metrics=metrics,
                )
            )
            pair_index += 1

    payload = {
        "schema_version": "arc-meta-result-v1",
        "meta_id": plan.meta_id,
        "meta_plan_digest": plan.plan_digest,
        "repository_count": len(studies),
        "analysis_unit": "repository_cluster",
        "bootstrap_samples": plan.bootstrap_samples,
        "ci": plan.ci,
        "random_seed": plan.random_seed,
        "studies": [
            {
                "study_id": study.study_id,
                "benchmark_id": study.benchmark_id,
                "plan_digest": study.plan_digest,
                "artifact_dir": str(study.artifact_dir),
            }
            for study in studies
        ],
        "comparisons": [
            {
                "baseline_a": item.baseline_a,
                "baseline_b": item.baseline_b,
                "repository_wins_a": item.repository_wins_a,
                "repository_ties": item.repository_ties,
                "repository_wins_b": item.repository_wins_b,
                "metrics": {key: asdict(value) for key, value in item.metrics.items()},
            }
            for item in comparisons
        ],
    }
    (target / "meta_study.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_rows(target / "repository_effects.csv", repository_rows)
    _write_jsonl(target / "repository_effects.jsonl", repository_rows)
    _write_rows(target / "meta_effects.csv", metric_rows)
    _write_jsonl(target / "meta_effects.jsonl", metric_rows)

    file_paths = [
        target / "meta_study.json",
        target / "repository_effects.csv",
        target / "repository_effects.jsonl",
        target / "meta_effects.csv",
        target / "meta_effects.jsonl",
    ]
    manifest = {
        "meta_id": plan.meta_id,
        "meta_plan_digest": plan.plan_digest,
        "files": {path.name: _file_sha256(path) for path in file_paths},
    }
    (target / "meta_export_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return MetaStudyResult(
        meta_id=plan.meta_id,
        plan_digest=plan.plan_digest,
        repository_count=len(studies),
        studies=studies,
        comparisons=tuple(comparisons),
        artifact_dir=target,
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_study_plans(paths: Sequence[str | Path]) -> tuple[PreregisteredStudy, ...]:
    return tuple(load_preregistration(path) for path in paths)
