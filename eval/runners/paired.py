"""Isolated paired execution for normalized ARC context baselines."""

from __future__ import annotations

import itertools
import json
import random
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket
from eval.comparison import (
    PairedComparison,
    compare_paired_measurements,
    validate_comparable_manifests,
)
from eval.grading.hidden_tests import HiddenTestGrader
from eval.io import write_measurements_jsonl, write_summary_json
from eval.models import BenchmarkManifest, EvaluationSummary, TaskMeasurement
from eval.runners.experiment import ExperimentRunner, NORMALIZED_BASELINES
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore


@dataclass(frozen=True)
class BaselineRunResult:
    baseline: str
    initial_commit: str
    final_commit: str
    summary: EvaluationSummary
    measurements: tuple[TaskMeasurement, ...]
    event_count: int
    artifact_dir: Path


@dataclass(frozen=True)
class IsolatedPairedBenchmarkResult:
    run_id: str
    benchmark_id: str
    base_commit: str
    execution_order: tuple[str, ...]
    runs: dict[str, BaselineRunResult]
    comparisons: tuple[PairedComparison, ...]
    artifact_dir: Path


AgentFactory = Callable[[], AgentAdapter]


def blind_context_for_provider(context: ContextPacket) -> ContextPacket:
    """Remove treatment/operational labels while preserving actionable context.

    Real CLI adapters serialize the ContextPacket they receive. A paired study
    must not tell the model that it is running B3/B5/B7 or expose stale-memory
    flags and retrieval strategy IDs. The semantic memory/code content remains
    intact; only audit/control metadata is normalized or removed.
    """

    def _texts(items: list[dict]) -> list[dict]:
        blinded: list[dict] = []
        for item in items:
            kept = {key: item[key] for key in ("text", "confidence") if key in item}
            if kept:
                blinded.append(kept)
        return blinded

    return context.model_copy(
        update={
            "context_id": "CTX_BLINDED",
            "project_id": "benchmark",
            "state_version": 0,
            "compiled_event": 0,
            "context_policy": "BLINDED",
            "decisions": _texts(context.decisions),
            "assumptions": _texts(context.assumptions),
            "failures": _texts(context.failures),
            "procedures": _texts(context.procedures),
            "leases": [],
            "risk_flags": [],
            "budget_remaining_tokens": 0,
            "context_token_count": 0,
            "memory_ids": [],
            "stale_memory_ids": [],
            "retrieval_strategies": [],
            "digest": "",
        }
    )


class BlindedAgentAdapter:
    """Benchmark-only adapter wrapper that hides treatment labels from providers."""

    def __init__(self, delegate: AgentAdapter) -> None:
        self.delegate = delegate
        self.name = getattr(delegate, "name", None)

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        return await self.delegate.run(
            context=blind_context_for_provider(context),
            workspace=workspace,
            budget=budget,
        )


class IsolatedPairedBenchmarkRunner:
    """Run comparable manifests from independent Git + ARC state resets.

    Baselines are executed sequentially in an opaque, seed-shuffled order. Each
    treatment receives a detached integration worktree at the same canonical
    commit, a fresh EventStore, a fresh memory database, and a fresh agent
    object. Only audit artifacts survive workspace cleanup.
    """

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

    def _git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.source_repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "git command failed").strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
        return proc

    def _resolve_commit(self, ref: str) -> str:
        proc = self._git(["rev-parse", f"{ref}^{{commit}}"])
        return proc.stdout.strip()

    def _validate_manifests(self, manifests: Sequence[BenchmarkManifest]) -> tuple[str, int]:
        if len(manifests) < 2:
            raise ValueError("paired benchmark requires at least two baseline manifests")
        baselines = [manifest.baseline for manifest in manifests]
        if len(set(baselines)) != len(baselines):
            raise ValueError("paired benchmark baseline IDs must be unique")
        unsupported = sorted(set(baselines) - NORMALIZED_BASELINES)
        if unsupported:
            raise ValueError(f"unsupported normalized baselines: {', '.join(unsupported)}")
        benchmark_ids = {manifest.benchmark_id for manifest in manifests}
        if len(benchmark_ids) != 1:
            raise ValueError("paired benchmark manifests must share one benchmark_id")
        if any(manifest.hard_task_usd is None for manifest in manifests):
            raise ValueError("paired benchmark requires explicit hard_task_usd in every manifest")

        first = manifests[0]
        for other in manifests[1:]:
            validate_comparable_manifests(first, other)
        base_commit = self._resolve_commit(first.repo_commit)
        return base_commit, first.seed

    def _create_workspace(self, *, base_commit: str, run_id: str, slot: int) -> Path:
        run_root = self.workspace_root / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        workspace = run_root / f"w{slot:02d}-{uuid.uuid4().hex[:6]}"
        proc = self._git(["worktree", "add", "--detach", str(workspace), base_commit], check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "worktree creation failed").strip()
            raise RuntimeError(f"cannot create isolated benchmark worktree: {detail}")
        return workspace

    def _remove_workspace(self, workspace: Path) -> None:
        self._git(["worktree", "remove", "--force", str(workspace)], check=False)
        self._git(["worktree", "prune"], check=False)
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)

        # Orchestrator task worktrees/gate worktrees live beside the benchmark
        # integration worktree under `.arc-runtime/<workspace-name>`. Removing
        # the integration worktree alone would leave empty runtime scaffolding
        # that can be mistaken for cross-treatment state. Audit artifacts live
        # elsewhere and remain untouched.
        runtime_root = workspace.parent / ".arc-runtime" / workspace.name
        if runtime_root.exists():
            shutil.rmtree(runtime_root, ignore_errors=True)
        shared_runtime_root = workspace.parent / ".arc-runtime"
        if shared_runtime_root.exists():
            try:
                shared_runtime_root.rmdir()
            except OSError:
                pass

    @staticmethod
    def _materialize_manifest(orchestrator: Orchestrator, manifest: BenchmarkManifest) -> None:
        orchestrator.init_project(
            spec={
                "benchmark_id": manifest.benchmark_id,
                "repo_commit": manifest.repo_commit,
                "execution_mode": manifest.execution_mode,
            },
            constraints=list(manifest.project_constraints),
        )
        for task in manifest.tasks:
            orchestrator.create_task(
                task_id=task.task_id,
                goal=task.goal,
                task_type=task.task_type,
                required_capabilities=list(task.required_capabilities),
                dependencies=list(task.dependencies),
                files_declared=list(task.files),
                symbols=list(task.symbols),
                acceptance_criteria=list(task.acceptance),
                risk=task.risk,
                token_budget=task.token_budget,
            )

    @staticmethod
    def _write_events_jsonl(path: Path, events: list) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(
                    json.dumps(
                        event.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )

    @staticmethod
    def _write_manifest_json(path: Path, manifest: BenchmarkManifest) -> None:
        path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    async def run(
        self,
        manifests: Sequence[BenchmarkManifest],
        agent_factory: AgentFactory,
        *,
        run_id: str | None = None,
    ) -> IsolatedPairedBenchmarkResult:
        """Execute normalized baselines from independent reset environments."""
        manifest_list = list(manifests)
        base_commit, seed = self._validate_manifests(manifest_list)
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        artifact_root = self.output_root / manifest_list[0].benchmark_id / run_id
        if artifact_root.exists():
            raise ValueError(f"benchmark artifact directory already exists: {artifact_root}")
        artifact_root.mkdir(parents=True, exist_ok=False)

        execution = list(manifest_list)
        random.Random(seed).shuffle(execution)
        execution_order = tuple(manifest.baseline for manifest in execution)
        project_id = f"benchmark:{manifest_list[0].benchmark_id}"
        used_agents: list[AgentAdapter] = []
        agent_fingerprint: tuple[type, str | None] | None = None
        runs: dict[str, BaselineRunResult] = {}

        for slot, manifest in enumerate(execution, start=1):
            baseline_dir = artifact_root / manifest.baseline.lower()
            baseline_dir.mkdir(parents=True, exist_ok=False)
            workspace = self._create_workspace(base_commit=base_commit, run_id=run_id, slot=slot)
            event_store: EventStore | None = None
            memory_conn: sqlite3.Connection | None = None
            try:
                event_store = EventStore(baseline_dir / "state.db")
                memory_conn = sqlite3.connect(baseline_dir / "memory.db", check_same_thread=False)
                memory_conn.row_factory = sqlite3.Row
                memory = MemoryLifecycle(memory_conn)
                orchestrator = Orchestrator(
                    event_store,
                    memory,
                    workspace,
                    project_id,
                    verification_level=self.verification_level,
                    hard_task_usd=float(manifest.hard_task_usd),
                    hard_project_usd=self.hard_project_usd,
                    visible_test_cmd=self.visible_test_cmd or None,
                )
                self._materialize_manifest(orchestrator, manifest)

                agent = agent_factory()
                if any(agent is previous for previous in used_agents):
                    raise ValueError("agent_factory must return a fresh adapter instance per baseline")
                used_agents.append(agent)
                fingerprint = (type(agent), getattr(agent, "name", None))
                if agent_fingerprint is None:
                    agent_fingerprint = fingerprint
                elif fingerprint != agent_fingerprint:
                    raise ValueError(
                        "agent_factory changed adapter type/name across paired baselines"
                    )

                grader = HiddenTestGrader(self.hidden_test_dir) if self.hidden_test_dir else None
                runner = ExperimentRunner(grader=grader)
                summary = await runner.run_manifest(
                    orchestrator,
                    manifest,
                    BlindedAgentAdapter(agent),
                )
                measurements = tuple(runner.last_measurements)
                final_commit = self._git(["rev-parse", "HEAD"], cwd=workspace).stdout.strip()
                events = event_store.read_all(project_id=project_id)

                self._write_manifest_json(baseline_dir / "manifest.json", manifest)
                write_measurements_jsonl(baseline_dir / "measurements.jsonl", measurements)
                write_summary_json(baseline_dir / "summary.json", summary)
                self._write_events_jsonl(baseline_dir / "events.jsonl", events)
                (baseline_dir / "final_head.txt").write_text(final_commit + "\n", encoding="utf-8")

                runs[manifest.baseline] = BaselineRunResult(
                    baseline=manifest.baseline,
                    initial_commit=base_commit,
                    final_commit=final_commit,
                    summary=summary,
                    measurements=measurements,
                    event_count=len(events),
                    artifact_dir=baseline_dir,
                )
            except Exception as exc:
                (baseline_dir / "failure.json").write_text(
                    json.dumps(
                        {"baseline": manifest.baseline, "error": str(exc)},
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                raise
            finally:
                if memory_conn is not None:
                    memory_conn.close()
                if event_store is not None:
                    event_store.close()
                self._remove_workspace(workspace)

        comparisons: list[PairedComparison] = []
        for left, right in itertools.combinations(sorted(runs), 2):
            comparisons.append(
                compare_paired_measurements(
                    list(runs[left].measurements),
                    list(runs[right].measurements),
                )
            )

        metadata = {
            "run_id": run_id,
            "benchmark_id": manifest_list[0].benchmark_id,
            "base_commit": base_commit,
            "execution_order": list(execution_order),
            "baselines": {
                baseline: {
                    "initial_commit": result.initial_commit,
                    "final_commit": result.final_commit,
                    "event_count": result.event_count,
                    "artifact_dir": str(result.artifact_dir.relative_to(artifact_root)),
                }
                for baseline, result in sorted(runs.items())
            },
            "comparisons": [asdict(item) for item in comparisons],
        }
        (artifact_root / "paired_run.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        return IsolatedPairedBenchmarkResult(
            run_id=run_id,
            benchmark_id=manifest_list[0].benchmark_id,
            base_commit=base_commit,
            execution_order=execution_order,
            runs=runs,
            comparisons=tuple(comparisons),
            artifact_dir=artifact_root,
        )
