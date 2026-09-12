"""Concurrent multi-agent orchestration over the shared ARC application layer."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from application.routing import AgentRouter, RouteDecision
from state.models import GateStatus, TaskState

if TYPE_CHECKING:
    from application.app import ArcApplication


@dataclass
class OrchestrationResult:
    run_id: str
    policy: str
    rounds: int = 0
    routed: list[RouteDecision] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)

    @property
    def successful(self) -> bool:
        return not self.rejected and not self.failed


class OrchestrationEngine:
    """Route and execute independent READY tasks concurrently.

    Agent work may run concurrently, but each task still uses the normal ARC
    execution path and the Orchestrator's serialized integration boundary.
    """

    def __init__(
        self,
        app: "ArcApplication",
        *,
        policy: str = "balanced",
        max_parallel: int | None = None,
    ) -> None:
        self.app = app
        self.router = AgentRouter(policy)
        self.max_parallel = max_parallel or app.config.orchestration_max_parallel
        if self.max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")

    def _emit(self, kind: str, payload: dict, task_id: str | None = None) -> int:
        return self.app.event_store.append(
            actor="orchestrator",
            kind=kind,
            project_id=self.app.project_id,
            task_id=task_id,
            payload=payload,
        )

    @staticmethod
    def _surfaces(task: TaskState) -> set[str]:
        return {path for path in task.files_declared if path}

    def _select_batch(
        self,
        ready: list[TaskState],
        *,
        run_id: str,
        result: OrchestrationResult,
    ) -> list[tuple[TaskState, RouteDecision]]:
        doctor_rows = self.app.doctor_agents()
        doctor = {row.name: row for row in doctor_rows}
        profiles = self.app.list_agents()
        active_counts: dict[str, int] = {}
        occupied_surfaces: set[str] = set()
        batch: list[tuple[TaskState, RouteDecision]] = []

        # Risk-first gives high-risk work first access to the best matching
        # agent while remaining deterministic for equal-risk tasks.
        for task in sorted(ready, key=lambda item: (-item.risk, item.created_event, item.task_id)):
            if len(batch) >= self.max_parallel:
                break
            surfaces = self._surfaces(task)
            if surfaces.intersection(occupied_surfaces):
                result.deferred.append(task.task_id)
                self._emit(
                    "orchestration.deferred",
                    {
                        "run_id": run_id,
                        "reason": "overlapping_file_surface",
                        "files": sorted(surfaces.intersection(occupied_surfaces)),
                    },
                    task.task_id,
                )
                continue
            try:
                decision = self.router.route(
                    task,
                    profiles,
                    doctor,
                    active_counts,
                    default_agent=self.app.config.default_agent,
                )
            except RuntimeError as exc:
                result.deferred.append(task.task_id)
                self._emit(
                    "orchestration.deferred",
                    {"run_id": run_id, "reason": "no_route", "detail": str(exc)},
                    task.task_id,
                )
                continue

            batch.append((task, decision))
            occupied_surfaces.update(surfaces)
            active_counts[decision.agent_name] = active_counts.get(decision.agent_name, 0) + 1
            result.routed.append(decision)
            self._emit(
                "orchestration.routed",
                {
                    "run_id": run_id,
                    "agent": decision.agent_name,
                    "score": decision.score,
                    "policy": decision.policy,
                    "reasons": list(decision.reasons),
                    "task_type": task.task_type,
                    "required_capabilities": task.required_capabilities,
                },
                task.task_id,
            )
        return batch

    async def _execute_one(
        self,
        task: TaskState,
        decision: RouteDecision,
        *,
        run_id: str,
        result: OrchestrationResult,
    ) -> None:
        try:
            gate = await self.app.run_task(task.task_id, agent_name=decision.agent_name)
            if gate.status == GateStatus.ACCEPTED:
                result.accepted.append(task.task_id)
            else:
                result.rejected.append(task.task_id)
            self._emit(
                "orchestration.task_finished",
                {
                    "run_id": run_id,
                    "agent": decision.agent_name,
                    "gate_status": gate.status.value,
                    "gate_run_id": gate.gate_run_id,
                    "merged_commit_sha": gate.merged_commit_sha,
                    "rejection_stage": gate.rejection_stage,
                },
                task.task_id,
            )
        except Exception as exc:
            result.failed.append(task.task_id)
            self._emit(
                "orchestration.task_failed",
                {
                    "run_id": run_id,
                    "agent": decision.agent_name,
                    "error": str(exc),
                },
                task.task_id,
            )

    async def run_until_idle(self, *, max_rounds: int = 100) -> OrchestrationResult:
        self.app.require_initialized()
        run_id = f"orch_{uuid.uuid4().hex[:10]}"
        result = OrchestrationResult(run_id=run_id, policy=self.router.policy)
        self._emit(
            "orchestration.run_started",
            {
                "run_id": run_id,
                "policy": self.router.policy,
                "max_parallel": self.max_parallel,
            },
        )

        for round_index in range(1, max_rounds + 1):
            ready = self.app.orchestrator.scheduler.get_ready_tasks()
            if not ready:
                break
            batch = self._select_batch(ready, run_id=run_id, result=result)
            if not batch:
                # No route can currently make progress. Do not spin forever.
                break
            result.rounds = round_index
            self._emit(
                "orchestration.batch_started",
                {
                    "run_id": run_id,
                    "round": round_index,
                    "tasks": [task.task_id for task, _ in batch],
                    "agents": [decision.agent_name for _, decision in batch],
                },
            )
            await asyncio.gather(
                *(
                    self._execute_one(task, decision, run_id=run_id, result=result)
                    for task, decision in batch
                )
            )

        projection = self.app.projection()
        unresolved = [
            task.task_id
            for task in projection.dag.tasks.values()
            if task.status.value not in {"completed", "abandoned"}
        ]
        self._emit(
            "orchestration.run_finished",
            {
                "run_id": run_id,
                "policy": self.router.policy,
                "rounds": result.rounds,
                "accepted": result.accepted,
                "rejected": result.rejected,
                "failed": result.failed,
                "deferred": sorted(set(result.deferred)),
                "unresolved": unresolved,
            },
        )
        return result
