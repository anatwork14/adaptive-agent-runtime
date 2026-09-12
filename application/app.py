"""High-level ARC application service shared by CLI, TUI, and APIs."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from application.agents import AgentDoctorResult, build_agent, doctor_profile
from application.config import AgentProfile, ArcConfig, ConfigStore
from application.events import EventStream
from application.orchestration import OrchestrationEngine, OrchestrationResult
from application.planner import DeterministicPlanner, MissionPlan
from application.routing import AgentRouter, RouteDecision
from context.request import ContextRequest
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore
from state.models import Event, GateResult, TaskState, TaskStatus
from state.projection import DeterministicStateProjection


class ArcApplication:
    """Application boundary around ARC's authoritative runtime."""

    def __init__(self, repo: str | Path = ".", project_id: str | None = None) -> None:
        self.repo = Path(repo).resolve()
        self.arc_dir = self.repo / ".arc"
        self.config_store = ConfigStore(self.repo)
        self.config: ArcConfig = self.config_store.load(project_id)
        self.project_id = project_id or self.config.project_id
        self.config.project_id = self.project_id

        self.arc_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.arc_dir / "state.db"
        self.event_store = EventStore(self.db_path)
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.memory = MemoryLifecycle(self.connection)
        self.orchestrator = Orchestrator(
            self.event_store,
            self.memory,
            self.repo,
            self.project_id,
            hard_task_usd=self.config.hard_task_usd,
            hard_project_usd=self.config.hard_project_usd,
            visible_test_cmd=self.config.visible_test_cmd or None,
        )
        self.events = EventStream(self.event_store, self.project_id)

    def close(self) -> None:
        self.connection.close()
        self.event_store.close()

    def __enter__(self) -> "ArcApplication":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------
    def initialize(self, *, constraints: Optional[list[str]] = None) -> int:
        existing = self.event_store.read_all(project_id=self.project_id)
        created = next((event for event in existing if event.kind == "project.created"), None)
        if created:
            self.config_store.save(self.config)
            return created.id
        event_id = self.orchestrator.init_project(
            spec={"repo": str(self.repo)},
            constraints=constraints or [],
        )
        self.config_store.save(self.config)
        return event_id

    def require_initialized(self) -> None:
        events = self.event_store.read_all(project_id=self.project_id)
        if not any(event.kind == "project.created" for event in events):
            raise RuntimeError("No ARC project found. Run `arc init` first.")

    def projection(self) -> DeterministicStateProjection:
        self.require_initialized()
        return self.orchestrator.get_projection()

    def snapshot(self) -> dict:
        projection = self.projection()
        active_leases = [lease for lease in projection.leases.leases.values() if lease.is_active]
        return {
            "project_id": self.project_id,
            "version": projection.version,
            "project": projection.project.state,
            "tasks": list(projection.dag.tasks.values()),
            "budget": projection.budgets.state,
            "leases": active_leases,
            "agents": list(self.config.agents.values()),
            "orchestration": {
                "max_parallel": self.config.orchestration_max_parallel,
                "routing_policy": self.config.routing_policy,
            },
        }

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------
    def _next_task_id(self) -> str:
        ids = [task.task_id for task in self.list_tasks()]
        numbers = []
        for task_id in ids:
            match = re.fullmatch(r"T(\d+)", task_id)
            if match:
                numbers.append(int(match.group(1)))
        return f"T{max(numbers, default=0) + 1:03d}"

    def create_task(
        self,
        goal: str,
        *,
        task_id: str | None = None,
        task_type: str = "code",
        required_capabilities: Optional[list[str]] = None,
        dependencies: Optional[list[str]] = None,
        files: Optional[list[str]] = None,
        symbols: Optional[list[str]] = None,
        acceptance: Optional[list[str]] = None,
        risk: float = 0.5,
        token_budget: int = 24000,
    ) -> TaskState:
        self.require_initialized()
        if not goal.strip():
            raise ValueError("Task goal cannot be empty")
        dependencies = dependencies or []
        existing = {task.task_id for task in self.list_tasks()}
        missing = [dep for dep in dependencies if dep not in existing]
        if missing:
            raise ValueError(f"Unknown task dependencies: {', '.join(missing)}")
        task_id = task_id or self._next_task_id()
        if task_id in existing:
            raise ValueError(f"Task {task_id} already exists")
        self.orchestrator.create_task(
            task_id=task_id,
            goal=goal,
            task_type=task_type,
            required_capabilities=required_capabilities or [],
            dependencies=dependencies,
            files_declared=files or [],
            symbols=symbols or [],
            acceptance_criteria=acceptance or [],
            risk=risk,
            token_budget=token_budget,
        )
        task = self.get_task(task_id)
        if task is None:
            raise RuntimeError(f"Task {task_id} was not projected after creation")
        return task

    def list_tasks(self) -> list[TaskState]:
        projection = self.orchestrator.get_projection()
        return sorted(projection.dag.tasks.values(), key=lambda task: task.created_event)

    def get_task(self, task_id: str) -> TaskState | None:
        return self.orchestrator.scheduler.get_task(task_id)

    def retry_task(self, task_id: str, *, reason: str = "manual retry") -> TaskState:
        self.require_initialized()
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status not in {TaskStatus.FAILED, TaskStatus.BLOCKED}:
            raise ValueError(f"Task {task_id} is {task.status.value}; only failed/blocked tasks can retry")
        self.event_store.append(
            actor="operator",
            kind="recovery.retry",
            project_id=self.project_id,
            task_id=task_id,
            payload={"reason": reason, "attempt": task.attempt_count + 1},
        )
        refreshed = self.get_task(task_id)
        assert refreshed is not None
        return refreshed

    def cancel_task(self, task_id: str, *, reason: str = "operator cancelled") -> TaskState:
        self.require_initialized()
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status == TaskStatus.COMPLETED:
            raise ValueError(f"Task {task_id} is already completed")
        if task.status == TaskStatus.ABANDONED:
            return task
        self.event_store.append(
            actor="operator",
            kind="task.abandoned",
            project_id=self.project_id,
            task_id=task_id,
            payload={"reason": reason},
        )
        refreshed = self.get_task(task_id)
        assert refreshed is not None
        return refreshed

    async def run_task(self, task_id: str, *, agent_name: str | None = None) -> GateResult:
        self.require_initialized()
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status != TaskStatus.READY:
            raise ValueError(
                f"Task {task_id} is {task.status.value}; it must be ready before execution"
            )
        name = agent_name or self.config.default_agent
        profile = self.config.agents.get(name)
        if not profile:
            raise ValueError(f"Agent profile {name!r} not found")
        adapter = build_agent(profile)
        return await self.orchestrator.execute_task(task_id, adapter, name)

    # ------------------------------------------------------------------
    # Planning, routing, and orchestration
    # ------------------------------------------------------------------
    def plan_objective(
        self,
        objective: str,
        *,
        files: Optional[list[str]] = None,
        acceptance: Optional[list[str]] = None,
        risk: float = 0.5,
        token_budget: int = 24000,
        max_tasks: int = 8,
    ) -> tuple[MissionPlan, list[TaskState]]:
        """Create a deterministic mission plan and materialize its task DAG."""
        self.require_initialized()
        plan = DeterministicPlanner().plan(
            objective,
            files=files,
            acceptance=acceptance,
            risk=risk,
            token_budget=token_budget,
            max_tasks=max_tasks,
        )
        key_to_task_id: dict[str, str] = {}
        created: list[TaskState] = []
        for item in plan.tasks:
            dependencies = [key_to_task_id[key] for key in item.dependencies]
            task = self.create_task(
                item.goal,
                task_type=item.task_type,
                required_capabilities=item.required_capabilities,
                dependencies=dependencies,
                files=item.files,
                acceptance=item.acceptance,
                risk=item.risk,
                token_budget=item.token_budget,
            )
            key_to_task_id[item.key] = task.task_id
            created.append(task)

        self.event_store.append(
            actor="planner",
            kind="orchestration.plan_created",
            project_id=self.project_id,
            payload={
                "objective": objective,
                "planner": plan.planner,
                "tasks": [
                    {
                        "key": item.key,
                        "task_id": key_to_task_id[item.key],
                        "task_type": item.task_type,
                        "dependencies": [key_to_task_id[key] for key in item.dependencies],
                        "files": item.files,
                        "required_capabilities": item.required_capabilities,
                    }
                    for item in plan.tasks
                ],
            },
        )
        return plan, created

    def route_task(self, task_id: str, *, policy: str | None = None) -> RouteDecision:
        self.require_initialized()
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        doctors = {item.name: item for item in self.doctor_agents()}
        router = AgentRouter(policy or self.config.routing_policy)
        return router.route(
            task,
            self.list_agents(),
            doctors,
            default_agent=self.config.default_agent,
        )

    async def orchestrate(
        self,
        *,
        policy: str | None = None,
        max_parallel: int | None = None,
        max_rounds: int = 100,
    ) -> OrchestrationResult:
        engine = OrchestrationEngine(
            self,
            policy=policy or self.config.routing_policy,
            max_parallel=max_parallel or self.config.orchestration_max_parallel,
        )
        return await engine.run_until_idle(max_rounds=max_rounds)

    # ------------------------------------------------------------------
    # Agents and configuration
    # ------------------------------------------------------------------
    def list_agents(self) -> list[AgentProfile]:
        return sorted(self.config.agents.values(), key=lambda profile: profile.name)

    def add_agent(self, profile: AgentProfile, *, make_default: bool = False) -> AgentProfile:
        self.config.agents[profile.name] = profile
        if make_default:
            self.config.default_agent = profile.name
        self.config_store.save(self.config)
        return profile

    def doctor_agents(self, names: Optional[Iterable[str]] = None) -> list[AgentDoctorResult]:
        selected = set(names or self.config.agents.keys())
        unknown = selected.difference(self.config.agents)
        if unknown:
            raise ValueError(f"Unknown agent profiles: {', '.join(sorted(unknown))}")
        return [doctor_profile(self.config.agents[name]) for name in sorted(selected)]

    # ------------------------------------------------------------------
    # Inspection services
    # ------------------------------------------------------------------
    def recent_events(self, *, after: int = 0, limit: int = 50) -> list[Event]:
        self.require_initialized()
        return self.event_store.read_after(after, project_id=self.project_id, limit=limit)

    def task_events(self, task_id: str, *, limit: int = 100) -> list[Event]:
        events = self.event_store.read_all(project_id=self.project_id)
        return [event for event in events if event.task_id == task_id][-limit:]

    def compile_context(self, task_id: str, *, agent_name: str | None = None):
        self.require_initialized()
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        projection = self.projection()
        name = agent_name or self.config.default_agent
        request = ContextRequest(
            context_request_id=f"CR_{task_id}_{projection.version}",
            project_id=self.project_id,
            task_id=task_id,
            agent_id=name,
            state_version=projection.version,
            goal=task.goal,
            risk=task.risk,
            files_declared=task.files_declared,
            symbols=task.symbols,
            dependencies=task.dependencies,
            token_budget=task.token_budget,
        )
        retrieval = self.orchestrator.retriever.retrieve(request)
        return self.orchestrator.compiler.compile(
            request=request,
            retrieval=retrieval,
            project_state=projection.project.state,
            task_state=task,
            active_leases=[],
        )
