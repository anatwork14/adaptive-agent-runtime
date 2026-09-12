"""Repeated isolated paired trials and aggregate research statistics."""

from __future__ import annotations

import hashlib
import json
import platform
import random
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable, Sequence

from adapters.base import AgentAdapter
from eval.analysis.stats import BootstrapResult, StatisticalAnalyzer
from eval.models import BenchmarkManifest
from eval.runners.paired import (
    IsolatedPairedBenchmarkResult,
    IsolatedPairedBenchmarkRunner,
)


@dataclass(frozen=True)
class AggregateMetric:
    """Bootstrap summary over per-repetition paired deltas (baseline A - baseline B)."""

    sample_count: int
    mean_delta: float | None
    median_delta: float | None
    ci_lower: float | None
    ci_upper: float | None


@dataclass(frozen=True)
class AggregatePairedComparison:
    """Aggregate comparison where one paired triplet repetition is the sampling unit."""

    baseline_a: str
    baseline_b: str
    repetitions: int
    wins_a: int
    wins_b: int
    ties: int
    resolved_rate_delta: AggregateMetric
    mean_context_tokens_delta: AggregateMetric
    mean_provider_tokens_delta: AggregateMetric
    mean_cost_usd_delta: AggregateMetric
    p95_end_to_end_latency_ms_delta: AggregateMetric
    stale_delivery_rate_delta: AggregateMetric


@dataclass(frozen=True)
class RepeatedPairedBenchmarkResult:
    study_id: str
    benchmark_id: str
    base_commit: str
    repeat_count: int
    repeat_seeds: tuple[int, ...]
    repeats: tuple[IsolatedPairedBenchmarkResult, ...]
    aggregates: tuple[AggregatePairedComparison, ...]
    provenance: dict[str, Any]
    artifact_dir: Path


AgentFactory = Callable[[], AgentAdapter]


def balanced_execution_orders(
    baselines: Sequence[str],
    repeats: int,
    *,
    random_seed: int,
) -> tuple[tuple[str, ...], ...]:
    """Create deterministic crossover blocks that balance treatment positions.

    A complete block contains one cyclic rotation per baseline, so every
    treatment appears exactly once in every ordinal position. Alternate blocks
    reverse the orientation, reducing simple carryover/order effects. Row order
    inside each block is seed-shuffled.
    """
    labels = sorted(set(baselines))
    if len(labels) < 2:
        raise ValueError("balanced execution schedule requires at least two baselines")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")

    rng = random.Random(random_seed)
    base = list(labels)
    rng.shuffle(base)
    orders: list[tuple[str, ...]] = []
    block = 0
    while len(orders) < repeats:
        orientation = list(base) if block % 2 == 0 else list(reversed(base))
        rows = [
            tuple(orientation[index:] + orientation[:index])
            for index in range(len(orientation))
        ]
        rng.shuffle(rows)
        for row in rows:
            if len(orders) >= repeats:
                break
            orders.append(row)
        block += 1
        if block % 2 == 0:
            rng.shuffle(base)
    return tuple(orders)


def _shuffled_order(seed: int, baselines: Sequence[str]) -> tuple[str, ...]:
    labels = sorted(set(baselines))
    random.Random(seed).shuffle(labels)
    return tuple(labels)


def _balanced_seed_schedule(
    baselines: Sequence[str],
    orders: Sequence[tuple[str, ...]],
    *,
    base_seed: int,
) -> tuple[int, ...]:
    """Find unique manifest seeds that reproduce the planned v0.13 shuffle orders."""
    labels = sorted(set(baselines))
    cursor = base_seed
    selected: list[int] = []
    for target in orders:
        for _ in range(100000):
            candidate = cursor
            cursor += 1
            if candidate in selected:
                continue
            if _shuffled_order(candidate, labels) == tuple(target):
                selected.append(candidate)
                break
        else:
            raise RuntimeError(
                f"unable to find deterministic seed for execution order {target}"
            )
    return tuple(selected)


def _bootstrap_metric(
    deltas: list[float],
    *,
    n_bootstraps: int,
    ci: float,
    random_seed: int,
) -> AggregateMetric:
    if not deltas:
        return AggregateMetric(
            sample_count=0,
            mean_delta=None,
            median_delta=None,
            ci_lower=None,
            ci_upper=None,
        )
    estimate: BootstrapResult = StatisticalAnalyzer.bootstrap_ci(
        deltas,
        n_bootstraps=n_bootstraps,
        ci=ci,
        random_seed=random_seed & 0xFFFFFFFF,
    )
    return AggregateMetric(
        sample_count=len(deltas),
        mean_delta=estimate.mean,
        median_delta=estimate.median,
        ci_lower=estimate.ci_lower,
        ci_upper=estimate.ci_upper,
    )


def _paired_summary_deltas(
    repetitions: Sequence[IsolatedPairedBenchmarkResult],
    baseline_a: str,
    baseline_b: str,
    field: str,
) -> list[float]:
    values: list[float] = []
    for repetition in repetitions:
        summary_a = repetition.runs[baseline_a].summary
        summary_b = repetition.runs[baseline_b].summary
        left = getattr(summary_a, field)
        right = getattr(summary_b, field)
        if left is None or right is None:
            continue
        values.append(float(left) - float(right))
    return values


def aggregate_repeated_results(
    repetitions: Sequence[IsolatedPairedBenchmarkResult],
    *,
    n_bootstraps: int = 2000,
    ci: float = 0.95,
    random_seed: int = 42,
) -> tuple[AggregatePairedComparison, ...]:
    """Aggregate paired runs without pretending tasks inside one run are independent."""
    runs = list(repetitions)
    if len(runs) < 2:
        raise ValueError("aggregate repeated comparison requires at least two repetitions")
    if n_bootstraps < 1:
        raise ValueError("n_bootstraps must be >= 1")
    if not 0.0 < ci < 1.0:
        raise ValueError("ci must be between 0 and 1")

    benchmark_ids = {item.benchmark_id for item in runs}
    base_commits = {item.base_commit for item in runs}
    baseline_sets = {tuple(sorted(item.runs)) for item in runs}
    if len(benchmark_ids) != 1:
        raise ValueError("repeated results mix benchmark IDs")
    if len(base_commits) != 1:
        raise ValueError("repeated results mix repository base commits")
    if len(baseline_sets) != 1:
        raise ValueError("repeated results mix baseline sets")

    baselines = next(iter(baseline_sets))
    comparisons: list[AggregatePairedComparison] = []
    metric_fields = (
        "mean_context_tokens",
        "mean_provider_tokens",
        "mean_cost_usd",
        "p95_end_to_end_latency_ms",
        "stale_delivery_rate",
    )

    pair_index = 0
    for left_index in range(len(baselines)):
        for right_index in range(left_index + 1, len(baselines)):
            baseline_a = baselines[left_index]
            baseline_b = baselines[right_index]
            resolved_deltas = _paired_summary_deltas(
                runs, baseline_a, baseline_b, "resolved_rate"
            )
            wins_a = sum(1 for value in resolved_deltas if value > 0.0)
            wins_b = sum(1 for value in resolved_deltas if value < 0.0)
            ties = len(resolved_deltas) - wins_a - wins_b

            offset = pair_index * 100
            metrics = {
                field: _bootstrap_metric(
                    _paired_summary_deltas(runs, baseline_a, baseline_b, field),
                    n_bootstraps=n_bootstraps,
                    ci=ci,
                    random_seed=random_seed + offset + idx + 1,
                )
                for idx, field in enumerate(metric_fields)
            }
            comparisons.append(
                AggregatePairedComparison(
                    baseline_a=baseline_a,
                    baseline_b=baseline_b,
                    repetitions=len(runs),
                    wins_a=wins_a,
                    wins_b=wins_b,
                    ties=ties,
                    resolved_rate_delta=_bootstrap_metric(
                        resolved_deltas,
                        n_bootstraps=n_bootstraps,
                        ci=ci,
                        random_seed=random_seed + offset,
                    ),
                    mean_context_tokens_delta=metrics["mean_context_tokens"],
                    mean_provider_tokens_delta=metrics["mean_provider_tokens"],
                    mean_cost_usd_delta=metrics["mean_cost_usd"],
                    p95_end_to_end_latency_ms_delta=metrics[
                        "p95_end_to_end_latency_ms"
                    ],
                    stale_delivery_rate_delta=metrics["stale_delivery_rate"],
                )
            )
            pair_index += 1

    return tuple(comparisons)


def _manifest_digest(manifest: BenchmarkManifest) -> str:
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _agent_fingerprint(agent: AgentAdapter) -> dict[str, Any]:
    cls = agent.__class__
    return {
        "adapter_type": f"{cls.__module__}.{cls.__qualname__}",
        "name": getattr(agent, "name", None),
        "provider": getattr(agent, "provider", None),
        "model_name": getattr(agent, "model_name", None),
        "executable": getattr(agent, "executable", None),
    }


def _arc_version() -> str:
    try:
        return version("adaptive-agent-runtime")
    except PackageNotFoundError:
        return "unknown"


def _git_version() -> str:
    proc = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


class RepeatedPairedBenchmarkRunner:
    """Execute N independent paired triplets and aggregate repetition-level deltas."""

    def __init__(
        self,
        source_repo: str | Path,
        *,
        output_root: str | Path | None = None,
        workspace_root: str | Path | None = None,
        verification_level: str = "V0",
        visible_test_cmd: list[str] | None = None,
        hard_project_usd: float = 500.0,
        hidden_test_dir: str | Path | None = None,
    ) -> None:
        self.source_repo = Path(source_repo).resolve()
        self.output_root = Path(output_root).resolve() if output_root else (
            self.source_repo.parent / ".arc-benchmark-results" / self.source_repo.name
        )
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else (
            self.source_repo.parent / ".arc-benchmark-runtime" / self.source_repo.name
        )
        self.verification_level = verification_level
        self.visible_test_cmd = list(visible_test_cmd or [])
        self.hard_project_usd = hard_project_usd
        self.hidden_test_dir = Path(hidden_test_dir).resolve() if hidden_test_dir else None
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_base_manifests(manifests: Sequence[BenchmarkManifest]) -> list[BenchmarkManifest]:
        manifest_list = list(manifests)
        if len(manifest_list) < 2:
            raise ValueError("repeated paired benchmark requires at least two manifests")
        benchmark_ids = {manifest.benchmark_id for manifest in manifest_list}
        seeds = {manifest.seed for manifest in manifest_list}
        profiles = {manifest.agent_profile for manifest in manifest_list}
        models = {manifest.model for manifest in manifest_list}
        if len(benchmark_ids) != 1:
            raise ValueError("repeated paired manifests must share one benchmark_id")
        if len(seeds) != 1:
            raise ValueError("repeated paired manifests must share one base seed")
        if len(profiles) != 1:
            raise ValueError("repeated paired manifests must share one agent_profile")
        if len(models) != 1:
            raise ValueError("repeated paired manifests must share one model")
        return manifest_list

    async def run(
        self,
        manifests: Sequence[BenchmarkManifest],
        agent_factory: AgentFactory,
        *,
        repeats: int = 5,
        study_id: str | None = None,
        n_bootstraps: int = 2000,
        ci: float = 0.95,
        provenance_extra: dict[str, Any] | None = None,
    ) -> RepeatedPairedBenchmarkResult:
        """Run independent reset-safe triplets and persist study-level provenance."""
        manifest_list = self._validate_base_manifests(manifests)
        if repeats < 2:
            raise ValueError("repeated paired benchmark requires repeats >= 2")
        if n_bootstraps < 1:
            raise ValueError("n_bootstraps must be >= 1")
        if not 0.0 < ci < 1.0:
            raise ValueError("ci must be between 0 and 1")

        benchmark_id = manifest_list[0].benchmark_id
        base_seed = manifest_list[0].seed
        study_id = study_id or f"study-{uuid.uuid4().hex[:12]}"
        artifact_root = self.output_root / benchmark_id / "studies" / study_id
        if artifact_root.exists():
            raise ValueError(f"study artifact directory already exists: {artifact_root}")
        artifact_root.mkdir(parents=True, exist_ok=False)

        planned_orders = balanced_execution_orders(
            [manifest.baseline for manifest in manifest_list],
            repeats,
            random_seed=base_seed,
        )
        repeat_seeds = _balanced_seed_schedule(
            [manifest.baseline for manifest in manifest_list],
            planned_orders,
            base_seed=base_seed,
        )
        seen_agents: list[AgentAdapter] = []
        expected_agent_fingerprint: dict[str, Any] | None = None

        def fresh_factory() -> AgentAdapter:
            nonlocal expected_agent_fingerprint
            agent = agent_factory()
            if any(agent is previous for previous in seen_agents):
                raise ValueError(
                    "agent_factory must return a fresh adapter instance for every "
                    "treatment across every repetition"
                )
            seen_agents.append(agent)
            fingerprint = _agent_fingerprint(agent)
            if expected_agent_fingerprint is None:
                expected_agent_fingerprint = fingerprint
            elif fingerprint != expected_agent_fingerprint:
                raise ValueError(
                    "agent_factory changed adapter fingerprint across repeated paired trials"
                )
            return agent

        repeated_results: list[IsolatedPairedBenchmarkResult] = []
        study_workspace_root = self.workspace_root / study_id
        inner_output_root = artifact_root / "repeats"
        try:
            for index, (seed, planned_order) in enumerate(
                zip(repeat_seeds, planned_orders),
                start=1,
            ):
                repeated_manifests = [
                    manifest.model_copy(update={"seed": seed}, deep=True)
                    for manifest in manifest_list
                ]
                runner = IsolatedPairedBenchmarkRunner(
                    self.source_repo,
                    output_root=inner_output_root,
                    workspace_root=study_workspace_root,
                    verification_level=self.verification_level,
                    visible_test_cmd=self.visible_test_cmd or None,
                    hard_project_usd=self.hard_project_usd,
                    hidden_test_dir=self.hidden_test_dir,
                )
                repeat_result = await runner.run(
                    repeated_manifests,
                    fresh_factory,
                    run_id=f"{study_id}-r{index:03d}-s{seed}",
                )
                if repeat_result.execution_order != planned_order:
                    raise RuntimeError(
                        "paired runner execution order diverged from balanced schedule: "
                        f"planned={planned_order}, actual={repeat_result.execution_order}"
                    )
                repeated_results.append(repeat_result)

            aggregates = aggregate_repeated_results(
                repeated_results,
                n_bootstraps=n_bootstraps,
                ci=ci,
                random_seed=base_seed,
            )
            base_commits = {item.base_commit for item in repeated_results}
            if len(base_commits) != 1:
                raise RuntimeError("repeated paired runner produced inconsistent base commits")
            base_commit = next(iter(base_commits))

            runtime = {
                "arc_version": _arc_version(),
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "git_version": _git_version(),
                "verification_level": self.verification_level,
                "visible_test_cmd": list(self.visible_test_cmd),
                "hard_project_usd": self.hard_project_usd,
                "hidden_tests_enabled": self.hidden_test_dir is not None,
            }
            provenance = {
                "study_id": study_id,
                "benchmark_id": benchmark_id,
                "base_commit": base_commit,
                "base_seed": base_seed,
                "order_schedule": "balanced_crossover_v1",
                "planned_execution_orders": [list(order) for order in planned_orders],
                "repeat_seeds": list(repeat_seeds),
                "repeat_count": repeats,
                "n_bootstraps": n_bootstraps,
                "ci": ci,
                "agent_profile": manifest_list[0].agent_profile,
                "declared_model": manifest_list[0].model,
                "agent_fingerprint": expected_agent_fingerprint,
                "manifest_digests": {
                    manifest.baseline: _manifest_digest(manifest)
                    for manifest in sorted(manifest_list, key=lambda item: item.baseline)
                },
                "runtime": runtime,
                "extra": dict(provenance_extra or {}),
            }

            (artifact_root / "provenance.json").write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (artifact_root / "aggregates.json").write_text(
                json.dumps(
                    [asdict(item) for item in aggregates],
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            study_payload = {
                "study_id": study_id,
                "benchmark_id": benchmark_id,
                "base_commit": base_commit,
                "repeat_count": repeats,
                "repeat_seeds": list(repeat_seeds),
                "order_schedule": "balanced_crossover_v1",
                "repetitions": [
                    {
                        "run_id": item.run_id,
                        "execution_order": list(item.execution_order),
                        "artifact_dir": str(item.artifact_dir.relative_to(artifact_root)),
                    }
                    for item in repeated_results
                ],
                "aggregate_pairs": [
                    f"{item.baseline_a}-{item.baseline_b}" for item in aggregates
                ],
            }
            (artifact_root / "study.json").write_text(
                json.dumps(study_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            return RepeatedPairedBenchmarkResult(
                study_id=study_id,
                benchmark_id=benchmark_id,
                base_commit=base_commit,
                repeat_count=repeats,
                repeat_seeds=repeat_seeds,
                repeats=tuple(repeated_results),
                aggregates=aggregates,
                provenance=provenance,
                artifact_dir=artifact_root,
            )
        except Exception as exc:
            (artifact_root / "failure.json").write_text(
                json.dumps(
                    {"study_id": study_id, "error": str(exc)},
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            raise
        finally:
            if study_workspace_root.exists():
                shutil.rmtree(study_workspace_root, ignore_errors=True)
