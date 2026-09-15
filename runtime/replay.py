"""Deterministic event replay engine."""

from typing import Optional

from state.events import EventStore
from state.projection import DeterministicStateProjection


class ReplayEngine:
    """Replays the authoritative event store to deterministically reconstruct project state."""

    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store

    def replay_project(
        self,
        project_id: str,
        upto_event_id: Optional[int] = None,
    ) -> DeterministicStateProjection:
        """Replay events from start up to specified event_id (or latest)."""
        events = self.event_store.read_all(project_id=project_id)
        if upto_event_id is not None:
            events = [e for e in events if e.id <= upto_event_id]

        projection = DeterministicStateProjection(project_id)
        for ev in events:
            projection.apply(ev)
        return projection

    def verify_replay_consistency(self, project_id: str) -> bool:
        """Verify that two independent replays yield identical state projections."""
        proj1 = self.replay_project(project_id)
        proj2 = self.replay_project(project_id)

        assert proj1.version == proj2.version
        assert proj1.project.state.model_dump() == proj2.project.state.model_dump()
        assert {k: v.model_dump() for k, v in proj1.dag.tasks.items()} == {
            k: v.model_dump() for k, v in proj2.dag.tasks.items()
        }
        assert proj1.budgets.state.model_dump() == proj2.budgets.state.model_dump()
        return True
