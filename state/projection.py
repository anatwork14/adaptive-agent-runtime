"""Deterministic projections for the Authoritative State Plane."""

from typing import Dict, List, Optional
from state.models import (
    BudgetState,
    Event,
    Lease,
    ProjectState,
    TaskState,
    TaskStatus,
)


class ProjectProjector:
    """Project authoritative state for a single project from event stream."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.state = ProjectState(project_id=project_id)

    def apply(self, event: Event) -> None:
        if event.project_id != self.project_id:
            return

        self.state.version = event.id
        self.state.updated_at_event = event.id

        if event.kind == "project.created":
            self.state.created_at_event = event.id
            self.state.spec = event.payload.get("spec", {})
            self.state.constraints = list(event.payload.get("constraints", []))
            self.state.status = "active"

        elif event.kind == "project.spec_updated":
            new_spec = event.payload.get("spec", {})
            self.state.spec.update(new_spec)

        elif event.kind == "project.constraint_added":
            constraint = event.payload.get("constraint")
            if constraint and constraint not in self.state.constraints:
                self.state.constraints.append(constraint)

        elif event.kind == "project.constraint_removed":
            constraint = event.payload.get("constraint")
            if constraint in self.state.constraints:
                self.state.constraints.remove(constraint)

        elif event.kind == "task.created":
            task_id = event.task_id or event.payload.get("task_id")
            if task_id and task_id not in self.state.active_tasks:
                self.state.active_tasks.append(task_id)

        elif event.kind in ("task.failed", "task.abandoned"):
            task_id = event.task_id or event.payload.get("task_id")
            if task_id:
                if task_id in self.state.active_tasks:
                    self.state.active_tasks.remove(task_id)
                if task_id not in self.state.failed_tasks:
                    self.state.failed_tasks.append(task_id)

        elif event.kind in ("task.merged", "gate.accepted"):
            task_id = event.task_id or event.payload.get("task_id")
            if task_id:
                if task_id in self.state.active_tasks:
                    self.state.active_tasks.remove(task_id)
                if task_id not in self.state.completed_tasks:
                    self.state.completed_tasks.append(task_id)


class TaskDAGProjector:
    """Projects task DAG and execution states from event stream."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.tasks: Dict[str, TaskState] = {}

    def apply(self, event: Event) -> None:
        if event.project_id != self.project_id:
            return

        task_id = event.task_id or event.payload.get("task_id")

        if event.kind == "task.created" and task_id:
            payload = event.payload
            self.tasks[task_id] = TaskState(
                task_id=task_id,
                project_id=self.project_id,
                goal=payload.get("goal", ""),
                task_type=payload.get("task_type", "code"),
                risk=float(payload.get("risk", 0.5)),
                status=TaskStatus.READY if not payload.get("dependencies") else TaskStatus.CREATED,
                dependencies=list(payload.get("dependencies", [])),
                files_declared=list(payload.get("files_declared", [])),
                symbols=list(payload.get("symbols", [])),
                acceptance_criteria=list(payload.get("acceptance_criteria", [])),
                created_event=event.id,
                updated_event=event.id,
                token_budget=int(payload.get("token_budget", 24000)),
            )

        elif task_id and task_id in self.tasks:
            task = self.tasks[task_id]
            task.updated_event = event.id

            if event.kind == "task.dispatched":
                task.status = TaskStatus.DISPATCHED
                task.assigned_agent = event.payload.get("agent_id")
                task.dispatch_version = event.payload.get("state_version", event.id)
                task.attempt_count += 1

            elif event.kind == "task.submitted":
                task.status = TaskStatus.SUBMITTED

            elif event.kind == "task.blocked":
                task.status = TaskStatus.BLOCKED

            elif event.kind == "task.split":
                task.status = TaskStatus.SPLIT

            elif event.kind == "task.failed":
                task.status = TaskStatus.FAILED

            elif event.kind == "task.abandoned":
                task.status = TaskStatus.ABANDONED

            elif event.kind in ("task.merged", "gate.accepted"):
                task.status = TaskStatus.COMPLETED

            elif event.kind == "recovery.retry":
                task.status = TaskStatus.READY

        # Re-evaluate ready states for tasks whose dependencies just completed
        self._update_dependency_readiness()

    def _update_dependency_readiness(self) -> None:
        completed_ids = {tid for tid, t in self.tasks.items() if t.status == TaskStatus.COMPLETED}
        for task in self.tasks.values():
            if task.status == TaskStatus.CREATED:
                if all(dep in completed_ids for dep in task.dependencies):
                    task.status = TaskStatus.READY


class LeaseProjector:
    """Projects active resource leases and fencing tokens from event stream."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.leases: Dict[str, Lease] = {}
        self.current_fencing_token = 0

    def apply(self, event: Event) -> None:
        if event.project_id != self.project_id:
            return

        if event.kind == "lease.granted":
            resource = event.payload["resource"]
            token = event.fencing_token or (self.current_fencing_token + 1)
            self.current_fencing_token = max(self.current_fencing_token, token)
            self.leases[resource] = Lease(
                resource=resource,
                holder=event.payload["holder"],
                fencing_token=token,
                project_id=self.project_id,
                task_id=event.task_id,
                granted_at_event=event.id,
                expires_at_event=event.payload.get("expires_at_event"),
                is_active=True,
            )

        elif event.kind in ("lease.released", "lease.preempted", "lease.rejected"):
            resource = event.payload.get("resource")
            if resource and resource in self.leases:
                self.leases[resource].is_active = False

    def get_active_lease(self, resource: str) -> Optional[Lease]:
        lease = self.leases.get(resource)
        if lease and lease.is_active:
            return lease
        return None


class BudgetProjector:
    """Projects token and financial budget consumption from event stream."""

    def __init__(self, project_id: str, hard_task_usd: float = 5.0, hard_project_usd: float = 500.0) -> None:
        self.project_id = project_id
        self.state = BudgetState(
            project_id=project_id,
            hard_task_ceiling_usd=hard_task_usd,
            hard_project_ceiling_usd=hard_project_usd,
        )

    def apply(self, event: Event) -> None:
        if event.project_id != self.project_id:
            return

        payload = event.payload
        if event.kind == "budget.reserved":
            self.state.reserved_usd += float(payload.get("usd", 0.0))
            self.state.reserved_tokens += int(payload.get("tokens", 0))

        elif event.kind == "budget.consumed":
            usd = float(payload.get("usd", 0.0))
            tokens = int(payload.get("tokens", 0))
            self.state.consumed_usd += usd
            self.state.consumed_tokens += tokens
            if event.task_id:
                curr_task_usd = self.state.per_task_consumed_usd.get(event.task_id, 0.0)
                self.state.per_task_consumed_usd[event.task_id] = curr_task_usd + usd
                curr_task_tokens = self.state.per_task_consumed_tokens.get(event.task_id, 0)
                self.state.per_task_consumed_tokens[event.task_id] = curr_task_tokens + tokens


class DeterministicStateProjection:
    """Unified container for all authoritative projections for a project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.project = ProjectProjector(project_id)
        self.dag = TaskDAGProjector(project_id)
        self.leases = LeaseProjector(project_id)
        self.budgets = BudgetProjector(project_id)
        self.version = 0

    def apply(self, event: Event) -> None:
        self.project.apply(event)
        self.dag.apply(event)
        self.leases.apply(event)
        self.budgets.apply(event)
        self.version = event.id

    @classmethod
    def replay_from_events(cls, project_id: str, events: List[Event]) -> "DeterministicStateProjection":
        projection = cls(project_id)
        for ev in events:
            projection.apply(ev)
        return projection
