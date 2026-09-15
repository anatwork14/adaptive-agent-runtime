"""Financial and token budget accounting."""

from typing import Optional

from state.events import EventStore
from state.projection import BudgetProjector


class BudgetAccountant:
    """Enforces hard financial and token limits across tasks and the overall project."""

    def __init__(
        self,
        event_store: EventStore,
        project_id: str,
        hard_task_usd: float = 5.0,
        hard_project_usd: float = 500.0,
    ) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self.hard_task_usd = hard_task_usd
        self.hard_project_usd = hard_project_usd
        self.projector = BudgetProjector(project_id, hard_task_usd, hard_project_usd)

    def sync(self) -> None:
        events = self.event_store.read_all(project_id=self.project_id)
        self.projector = BudgetProjector(self.project_id, self.hard_task_usd, self.hard_project_usd)
        for ev in events:
            self.projector.apply(ev)

    def can_spend(self, task_id: Optional[str], estimated_usd: float) -> bool:
        self.sync()
        state = self.projector.state
        if state.consumed_usd + estimated_usd > self.hard_project_usd:
            return False
        if task_id:
            curr_task_usd = state.per_task_consumed_usd.get(task_id, 0.0)
            if curr_task_usd + estimated_usd > self.hard_task_usd:
                return False
        return True

    def reserve(self, usd: float, tokens: int, task_id: Optional[str] = None) -> None:
        self.event_store.append(
            actor="orchestrator",
            kind="budget.reserved",
            project_id=self.project_id,
            task_id=task_id,
            payload={"usd": usd, "tokens": tokens},
        )

    def record_consumption(self, usd: float, tokens: int, task_id: Optional[str] = None) -> None:
        self.event_store.append(
            actor="orchestrator",
            kind="budget.consumed",
            project_id=self.project_id,
            task_id=task_id,
            payload={"usd": usd, "tokens": tokens},
        )
        self.sync()
        if self.projector.state.consumed_usd >= self.hard_project_usd:
            self.event_store.append(
                actor="orchestrator",
                kind="budget.exhausted",
                project_id=self.project_id,
                payload={"reason": "project_ceiling_reached", "total_usd": self.projector.state.consumed_usd},
            )
