"""ARC-side observational service for Agent Bridge P6 collaboration runs.

Bridge collaboration state is useful operational evidence, but it is never an
ARC task-completion authority. This service records only minimized Bridge IDs,
status, cursors, and correlation metadata into ARC's append-only event log.

It deliberately does not call IntegrationGate and does not emit task.completed
or gate.accepted events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from integrations.agent_bridge import (
    AgentBridgeClient,
    BridgeDagRunProjection,
    BridgeIntegrationEvent,
)
from state.events import EventStore


@dataclass(frozen=True)
class BridgeCollaborationObservation:
    bridge_run_id: str
    bridge_session_id: str
    status: str
    task_id: str
    last_cursor: int = 0


class BridgeCollaborationObserver:
    """Record minimized Bridge collaboration evidence without mutating ARC task authority."""

    def __init__(
        self,
        *,
        client: AgentBridgeClient,
        event_store: EventStore,
        project_id: str,
    ) -> None:
        self.client = client
        self.event_store = event_store
        self.project_id = project_id

    def submit_for_task(
        self,
        *,
        task_id: str,
        submission: dict[str, Any],
        idempotency_key: str,
    ) -> BridgeCollaborationObservation:
        projection = self.client.submit_dag(
            submission,
            idempotency_key=idempotency_key,
        )
        self._assert_arc_correlation(projection, task_id)
        self._record_projection("bridge.collaboration_submitted", projection, task_id)
        return self._observation(projection, task_id)

    def refresh(
        self,
        *,
        task_id: str,
        bridge_run_id: str,
    ) -> BridgeCollaborationObservation:
        projection = self.client.get_dag_run(bridge_run_id)
        self._assert_arc_correlation(projection, task_id)
        self._record_projection("bridge.collaboration_observed", projection, task_id)
        return self._observation(projection, task_id)

    def replay(
        self,
        *,
        task_id: str,
        bridge_run_id: str,
        after_id: int = 0,
    ) -> list[BridgeIntegrationEvent]:
        events = self.client.replay_events(
            after_id=after_id,
            run_id=bridge_run_id,
        )
        for event in events:
            if event.run_id != bridge_run_id:
                raise ValueError("Bridge event run_id does not match requested run")
            correlation = event.correlation
            if (
                correlation is None
                or correlation.arc_project_id != self.project_id
                or correlation.arc_task_id != task_id
            ):
                raise ValueError("Bridge event correlation does not match ARC project/task")
            self.event_store.append(
                actor="agent_bridge",
                kind="bridge.collaboration_event_observed",
                project_id=self.project_id,
                task_id=task_id,
                payload={
                    "bridge_run_id": event.run_id,
                    "bridge_session_id": event.session_id,
                    "bridge_event_type": event.type,
                    "bridge_cursor": event.cursor,
                    "bridge_status_data": dict(event.data),
                },
            )
        return events

    def cancel(
        self,
        *,
        task_id: str,
        bridge_run_id: str,
    ) -> bool:
        cancelled = self.client.cancel_dag_run(bridge_run_id)
        self.event_store.append(
            actor="agent_bridge",
            kind="bridge.collaboration_cancel_requested",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "bridge_run_id": bridge_run_id,
                "cancelled": cancelled,
            },
        )
        return cancelled

    def _assert_arc_correlation(
        self,
        projection: BridgeDagRunProjection,
        task_id: str,
    ) -> None:
        correlation = projection.correlation
        if correlation is None:
            raise ValueError("Bridge run is missing ARC correlation metadata")
        if correlation.arc_project_id != self.project_id:
            raise ValueError("Bridge run correlation project does not match ARC project")
        if correlation.arc_task_id != task_id:
            raise ValueError("Bridge run correlation task does not match ARC task")

    def _record_projection(
        self,
        kind: str,
        projection: BridgeDagRunProjection,
        task_id: str,
    ) -> None:
        self.event_store.append(
            actor="agent_bridge",
            kind=kind,
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "bridge_run_id": projection.id,
                "bridge_session_id": projection.session_id,
                "bridge_status": projection.status,
                "bridge_failure_policy": projection.failure_policy,
                "bridge_max_parallel_turns": projection.max_parallel_turns,
                "bridge_participant_count": projection.participant_count,
                "bridge_node_count": projection.node_count,
            },
        )

    @staticmethod
    def _observation(
        projection: BridgeDagRunProjection,
        task_id: str,
    ) -> BridgeCollaborationObservation:
        return BridgeCollaborationObservation(
            bridge_run_id=projection.id,
            bridge_session_id=projection.session_id,
            status=projection.status,
            task_id=task_id,
        )
