"""Pre-registered multi-repository study suites and hierarchical aggregation."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from pydantic import BaseModel, Field, model_validator

from eval.studies.preregistration import (
    PreregisteredStudy,
    compute_plan_digest,
)


_METRIC_FIELDS = (
    "resolved_rate",
    "mean_context_tokens",
    "mean_provider_tokens",
    "mean_cost_usd",
    "p95_end_to_end_latency_ms",
    "stale_delivery_rate",
)


class SuiteMember(BaseModel):
    repo_id: str = Field(min_length=1)
    plan: PreregisteredStudy


class SuiteDesign(BaseModel):
    bootstrap_samples: int = Field(default=5000, ge=1)
    ci: float = Field(default=0.95, gt=0.0, lt=1.0)
    repository_weighting: str = "equal"
    bootstrap_unit: str = "repository_then_repetition"

    @model_validator(mode="after")
    def validate_design(self) -> "SuiteDesign":
        if self.repository_weighting != "equal":
            raise ValueError("v1 suite design requires equal repository weighting")
        if self.bootstrap_unit != "repository_then_repetition":
            raise ValueError("v1 suite design requires repository_then_repetition bootstrap")
        return self


class PreregisteredSuite(BaseModel):
    schema_version: str = "arc-preregistered-suite-v1"
    suite_id: str = Field(min_length=1)
    created_at_utc: str
    members: list[SuiteMember] = Field(min_length=2)
    design: SuiteDesign = Field(default_factory=SuiteDesign)
    suite_digest: str = ""

    @model_validator(mode="after")
    def validate_suite_contract(self) -> "PreregisteredSuite":
        if self.schema_version != "arc-preregistered-suite-v1":
            raise ValueError(f"unsupported suite schema: {self.schema_version}")
        repo_ids = [member.repo_id for member in self.members]
        if len(set(repo_ids)) != len(repo_ids):
            raise ValueError("suite repo_id values must be unique")
        for member in self.members:
            if member.plan.plan_digest != compute_plan_digest(member.plan):
                raise ValueError(f"member {member.repo_id} has invalid plan_digest")

        first = self.members[0].plan
        expected_baselines = tuple(sorted(manifest.baseline for manifest in first.manifests))
        expected_pairs = tuple(first.planned_comparisons)
        expected_metrics = tuple(first.design.primary_metrics)
        expected_protocol = (
            first.runtime.provider,
            first.runtime.model,
            first.design.repeats,
            first.design.bootstrap_samples,
            first.design.ci,
            first.design.order_schedule,
            first.design.analysis_unit,
        )
        for member in self.members[1:]:
            plan = member.plan
            baselines = tuple(sorted(manifest.baseline for manifest in plan.manifests))
            protocol = (
                plan.runtime.provider,
                plan.runtime.model,
                plan.design.repeats,
                plan.design.bootstrap_samples,
                plan.design.ci,
                plan.design.order_schedule,
                plan.design.analysis_unit,
            )
            if baselines != expected_baselines:
                raise ValueError(f"member {member.repo_id} baseline set differs")
            if tuple(plan.planned_comparisons) != expected_pairs:
                raise ValueError(f"member {member.repo_id} comparison set differs")
            if tuple(plan.design.primary_metrics) != expected_metrics:
                raise ValueError(f"member {member.repo_id} primary metrics differ")
            if protocol != expected_protocol:
                raise ValueError(f"member {member.repo_id} treatment protocol differs")
        return self


@dataclass(frozen=True)
class HierarchicalMetric:
    repository_count: int
    repetition_pair_count: int
    mean_delta: float | None
    median_repository_delta: float | None
    ci_lower: float | None
    ci_upper: float | None


@dataclass(frozen=True)
class HierarchicalPairAggregate:
    baseline_a: str
    baseline_b: str
    repository_count: int
    resolved_rate_delta: HierarchicalMetric
    mean_context_tokens_delta: HierarchicalMetric
    mean_provider_tokens_delta: HierarchicalMetric
    mean_cost_usd_delta: HierarchicalMetric
    p95_end_to_end_latency_ms_delta: HierarchicalMetric
    stale_delivery_rate_delta: HierarchicalMetric


@dataclass(frozen=True)
class SuiteAggregationResult:
    suite_id: str
    repository_count: int
    aggregates: tuple[HierarchicalPairAggregate, ...]
    artifact_dir: Path


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_suite_digest(suite: PreregisteredSuite | dict[str, Any]) -> str:
    payload = suite.model_dump(mode="json") if isinstance(suite, PreregisteredSuite) else dict(suite)
    payload["suite_digest"] = ""
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def create_suite(
    members: Mapping[str, PreregisteredStudy],
    *,
    suite_id: str,
    bootstrap_samples: int = 5000,
    ci: float = 0.95,
    created_at_utc: str | None = None,
) -> PreregisteredSuite:
    if len(members) < 2:
        raise ValueError("multi-repository suite requires at least two repositories")
    suite = PreregisteredSuite(
        suite_id=suite_id,
        created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat(),
        members=[
            SuiteMember(repo_id=repo_id, plan=plan.model_copy(deep=True))
            for repo_id, plan in sorted(members.items())
        ],
        design=SuiteDesign(bootstrap_samples=bootstrap_samples, ci=ci),
    )
    return suite.model_copy(update={"suite_digest": compute_suite_digest(suite)})


def save_suite(path: str | Path, suite: PreregisteredSuite) -> Path:
    if suite.suite_digest != compute_suite_digest(suite):
        raise ValueError("refusing to save suite with invalid suite_digest")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(suite.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_suite(path: str | Path) -> PreregisteredSuite:
    source = Path(path)
    suite = PreregisteredSuite.model_validate(json.loads(source.read_text(encoding="utf-8")))
    actual = compute_suite_digest(suite)
    if suite.suite_digest != actual:
        raise ValueError(
            f"suite digest mismatch: recorded={suite.suite_digest}, actual={actual}"
        )
    return suite


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"required suite study artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_study_against_plan(
    repo_id: str,
    plan: PreregisteredStudy,
    study_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    study = _read_json(study_dir / "study.json")
    provenance = _read_json(study_dir / "provenance.json")
    extra = provenance.get("extra", {})
    errors: list[str] = []
    if study.get("benchmark_id") != plan.benchmark_id:
        errors.append("benchmark_id")
    if study.get("base_commit") != plan.canonical_repo_commit:
        errors.append("base_commit")
    if study.get("repeat_count") != plan.design.repeats:
        errors.append("repeat_count")
    if study.get("order_schedule") != plan.design.order_schedule:
        errors.append("order_schedule")
    if provenance.get("n_bootstraps") != plan.design.bootstrap_samples:
        errors.append("bootstrap_samples")
    if provenance.get("ci") != plan.design.ci:
        errors.append("ci")
    if provenance.get("declared_model") != plan.runtime.model:
        errors.append("model")
    if provenance.get("runtime", {}).get("verification_level") != plan.runtime.verification_level:
        errors.append("verification_level")
    if provenance.get("runtime", {}).get("visible_test_cmd") != plan.runtime.visible_test_cmd:
        errors.append("visible_test_cmd")
    if provenance.get("runtime", {}).get("hard_project_usd") != plan.runtime.hard_project_usd:
        errors.append("hard_project_usd")
    if extra.get("plan_digest") != plan.plan_digest:
        errors.append("plan_digest")
    if extra.get("preregistered") is not True:
        errors.append("preregistered")
    if extra.get("preregistered_study_id") != plan.study_id:
        errors.append("preregistered_study_id")
    if errors:
        raise ValueError(
            f"study for repository {repo_id} does not match preregistered plan: "
            + ", ".join(errors)
        )
    return study, provenance


def _repetition_deltas(
    study_dir: Path,
    study: dict[str, Any],
    baseline_a: str,
    baseline_b: str,
    field: str,
) -> list[float]:
    values: list[float] = []
    for repetition in study.get("repetitions", []):
        repeat_root = study_dir / str(repetition["artifact_dir"])
        paired = _read_json(repeat_root / "paired_run.json")
        baselines = paired.get("baselines", {})
        if baseline_a not in baselines or baseline_b not in baselines:
            raise ValueError(
                f"repetition {repetition.get('run_id')} is missing paired baseline results"
            )
        summary_a = _read_json(
            repeat_root / str(baselines[baseline_a]["artifact_dir"]) / "summary.json"
        )
        summary_b = _read_json(
            repeat_root / str(baselines[baseline_b]["artifact_dir"]) / "summary.json"
        )
        left = summary_a.get(field)
        right = summary_b.get(field)
        if left is None or right is None:
            continue
        values.append(float(left) - float(right))
    return values


def _hierarchical_bootstrap(
    repository_deltas: Mapping[str, Sequence[float]],
    *,
    n_bootstraps: int,
    ci: float,
    random_seed: int,
) -> HierarchicalMetric:
    eligible = {
        repo_id: [float(value) for value in values]
        for repo_id, values in repository_deltas.items()
        if values
    }
    if not eligible:
        return HierarchicalMetric(0, 0, None, None, None, None)
    repo_ids = sorted(eligible)
    repo_means = [float(np.mean(eligible[repo_id])) for repo_id in repo_ids]
    point = float(np.mean(repo_means))
    median = float(np.median(repo_means))
    rng = np.random.default_rng(random_seed & 0xFFFFFFFF)
    estimates = np.empty(n_bootstraps, dtype=np.float64)
    for index in range(n_bootstraps):
        sampled_repo_indices = rng.integers(0, len(repo_ids), size=len(repo_ids))
        sampled_repo_means: list[float] = []
        for repo_index in sampled_repo_indices:
            values = eligible[repo_ids[int(repo_index)]]
            sampled = rng.choice(np.asarray(values, dtype=np.float64), size=len(values), replace=True)
            sampled_repo_means.append(float(np.mean(sampled)))
        estimates[index] = float(np.mean(sampled_repo_means))
    alpha = (1.0 - ci) / 2.0
    return HierarchicalMetric(
        repository_count=len(repo_ids),
        repetition_pair_count=sum(len(values) for values in eligible.values()),
        mean_delta=point,
        median_repository_delta=median,
        ci_lower=float(np.percentile(estimates, alpha * 100.0)),
        ci_upper=float(np.percentile(estimates, (1.0 - alpha) * 100.0)),
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def aggregate_suite_studies(
    suite: PreregisteredSuite,
    study_dirs: Mapping[str, str | Path],
    *,
    output_dir: str | Path,
) -> SuiteAggregationResult:
    """Aggregate completed preregistered studies with a two-stage cluster bootstrap."""
    if suite.suite_digest != compute_suite_digest(suite):
        raise ValueError("suite_digest is invalid")
    expected_ids = {member.repo_id for member in suite.members}
    provided_ids = set(study_dirs)
    if provided_ids != expected_ids:
        missing = sorted(expected_ids - provided_ids)
        extra = sorted(provided_ids - expected_ids)
        raise ValueError(f"suite study mapping mismatch: missing={missing}, extra={extra}")

    target = Path(output_dir).resolve()
    if target.exists():
        raise ValueError(f"suite aggregation output already exists: {target}")
    target.mkdir(parents=True, exist_ok=False)

    studies: dict[str, tuple[PreregisteredStudy, Path, dict[str, Any]]] = {}
    for member in suite.members:
        study_dir = Path(study_dirs[member.repo_id]).resolve()
        study, _ = _validate_study_against_plan(member.repo_id, member.plan, study_dir)
        studies[member.repo_id] = (member.plan, study_dir, study)

    baselines = sorted(manifest.baseline for manifest in suite.members[0].plan.manifests)
    pair_results: list[HierarchicalPairAggregate] = []
    repo_effect_rows: list[dict[str, Any]] = []
    hierarchical_rows: list[dict[str, Any]] = []
    pair_index = 0
    for baseline_a, baseline_b in itertools.combinations(baselines, 2):
        metric_results: dict[str, HierarchicalMetric] = {}
        for metric_index, field in enumerate(_METRIC_FIELDS):
            repository_deltas: dict[str, list[float]] = {}
            for repo_id, (_, study_dir, study) in studies.items():
                deltas = _repetition_deltas(
                    study_dir,
                    study,
                    baseline_a,
                    baseline_b,
                    field,
                )
                repository_deltas[repo_id] = deltas
                if deltas:
                    repo_effect_rows.append(
                        {
                            "suite_id": suite.suite_id,
                            "repo_id": repo_id,
                            "pair": f"{baseline_a}-{baseline_b}",
                            "baseline_a": baseline_a,
                            "baseline_b": baseline_b,
                            "metric": field,
                            "repetition_pairs": len(deltas),
                            "repository_mean_delta": float(np.mean(deltas)),
                            "repository_median_delta": float(np.median(deltas)),
                        }
                    )
            result = _hierarchical_bootstrap(
                repository_deltas,
                n_bootstraps=suite.design.bootstrap_samples,
                ci=suite.design.ci,
                random_seed=17041 + pair_index * 100 + metric_index,
            )
            metric_results[field] = result
            hierarchical_rows.append(
                {
                    "suite_id": suite.suite_id,
                    "pair": f"{baseline_a}-{baseline_b}",
                    "baseline_a": baseline_a,
                    "baseline_b": baseline_b,
                    "metric": field,
                    **asdict(result),
                }
            )
        pair_results.append(
            HierarchicalPairAggregate(
                baseline_a=baseline_a,
                baseline_b=baseline_b,
                repository_count=len(studies),
                resolved_rate_delta=metric_results["resolved_rate"],
                mean_context_tokens_delta=metric_results["mean_context_tokens"],
                mean_provider_tokens_delta=metric_results["mean_provider_tokens"],
                mean_cost_usd_delta=metric_results["mean_cost_usd"],
                p95_end_to_end_latency_ms_delta=metric_results[
                    "p95_end_to_end_latency_ms"
                ],
                stale_delivery_rate_delta=metric_results["stale_delivery_rate"],
            )
        )
        pair_index += 1

    (target / "suite.json").write_text(
        json.dumps(suite.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (target / "hierarchical_effects.json").write_text(
        json.dumps([asdict(item) for item in pair_results], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(target / "repository_effects.csv", repo_effect_rows)
    _write_csv(target / "hierarchical_effects.csv", hierarchical_rows)
    provenance = {
        "suite_id": suite.suite_id,
        "suite_digest": suite.suite_digest,
        "repository_count": len(studies),
        "repository_weighting": suite.design.repository_weighting,
        "bootstrap_unit": suite.design.bootstrap_unit,
        "bootstrap_samples": suite.design.bootstrap_samples,
        "ci": suite.design.ci,
        "members": {
            member.repo_id: {
                "plan_digest": member.plan.plan_digest,
                "preregistered_study_id": member.plan.study_id,
                "benchmark_id": member.plan.benchmark_id,
                "canonical_repo_commit": member.plan.canonical_repo_commit,
                "study_dir": str(Path(study_dirs[member.repo_id]).resolve()),
            }
            for member in suite.members
        },
    }
    (target / "suite_provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SuiteAggregationResult(
        suite_id=suite.suite_id,
        repository_count=len(studies),
        aggregates=tuple(pair_results),
        artifact_dir=target,
    )
