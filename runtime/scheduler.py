"""Task DAG Scheduler."""

from typing import List, Optional

from state.events import EventStore
from state.models import TaskState, TaskStatus
from state.projection import TaskDAGProjector


class TaskScheduler:
    """Schedules tasks based on dependency completion in the authoritative task DAG."""

    def __init__(self, event_store: EventStore, project_id: str) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self.projector = TaskDAGProjector(project_id)

    def sync(self) -> None:
        events = self.event_store.read_all(project_id=self.project_id)
        self.projector = TaskDAGProjector(self.project_id)
        for ev in events:
            self.projector.apply(ev)

    def get_ready_tasks(self) -> List[TaskState]:
        """Return tasks whose dependencies have all completed and are ready for dispatch."""
        self.sync()
        return [t for t in self.projector.tasks.values() if t.status == TaskStatus.READY]

    def get_task(self, task_id: str) -> Optional[TaskState]:
        self.sync()
        return self.projector.tasks.get(task_id)

    def dispatch_task(self, task_id: str, agent_id: str) -> None:
        """Mark task as dispatched in the authoritative event log."""
        state_version = self.event_store.current_version(self.project_id)
        self.event_store.append(
            actor="orchestrator",
            kind="task.dispatched",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "agent_id": agent_id,
                "state_version": state_version,
            },
        )
