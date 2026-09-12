"""Optimistic leasing and fencing token manager."""

from typing import Optional

from state.events import EventStore
from state.models import Lease
from state.projection import LeaseProjector


class LeaseManager:
    """Manage exclusive resource leases and monotonic fencing tokens."""

    def __init__(self, event_store: EventStore, project_id: str) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self._fencing_counter = 0

    def _projection(self) -> LeaseProjector:
        projector = LeaseProjector(self.project_id)
        for event in self.event_store.read_all(project_id=self.project_id):
            projector.apply(event)
        self._fencing_counter = max(self._fencing_counter, projector.current_fencing_token)
        return projector

    def request_lease(
        self,
        resource: str,
        holder: str,
        task_id: Optional[str] = None,
        ttl_events: Optional[int] = 100,
    ) -> Optional[Lease]:
        """Request an exclusive lease for a resource.

        Conflicts fail closed and are recorded as `lease.rejected`; callers may
        defer the task and retry after the active holder releases its lease.
        """
        projector = self._projection()
        active = projector.get_active_lease(resource)
        if active and active.holder != holder:
            self.event_store.append(
                actor="orchestrator",
                kind="lease.rejected",
                project_id=self.project_id,
                task_id=task_id,
                payload={
                    "resource": resource,
                    "holder": holder,
                    "active_holder": active.holder,
                    "active_task_id": active.task_id,
                    "reason": "resource_already_leased",
                },
            )
            return None

        self._fencing_counter += 1
        current_version = self.event_store.current_version(self.project_id)
        expires_at = (current_version + ttl_events) if ttl_events else None

        event_id = self.event_store.append(
            actor="orchestrator",
            kind="lease.granted",
            project_id=self.project_id,
            task_id=task_id,
            fencing_token=self._fencing_counter,
            payload={
                "resource": resource,
                "holder": holder,
                "fencing_token": self._fencing_counter,
                "expires_at_event": expires_at,
            },
        )

        return Lease(
            resource=resource,
            holder=holder,
            fencing_token=self._fencing_counter,
            project_id=self.project_id,
            task_id=task_id,
            granted_at_event=event_id,
            expires_at_event=expires_at,
            is_active=True,
        )

    def release_lease(self, resource: str, holder: str, task_id: Optional[str] = None) -> None:
        """Release an active lease."""
        self.event_store.append(
            actor="orchestrator",
            kind="lease.released",
            project_id=self.project_id,
            task_id=task_id,
            payload={"resource": resource, "holder": holder},
        )

    def validate_fencing_token(self, expected_token: int, current_token: int) -> bool:
        """Reject submission if fencing token is stale."""
        return current_token >= expected_token
