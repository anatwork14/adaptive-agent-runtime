"""Optimistic leasing and fencing token manager."""

from typing import Dict, Optional
from state.events import EventStore
from state.models import Lease


class LeaseManager:
    """Manages resource leases and monotonic fencing tokens to prevent concurrent write collisions."""

    def __init__(self, event_store: EventStore, project_id: str) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self._fencing_counter = 0

    def request_lease(
        self,
        resource: str,
        holder: str,
        task_id: Optional[str] = None,
        ttl_events: Optional[int] = 100,
    ) -> Optional[Lease]:
        """Request an exclusive lease for a resource."""
        self._fencing_counter += 1
        current_version = self.event_store.current_version(self.project_id)
        expires_at = (current_version + ttl_events) if ttl_events else None

        self.event_store.append(
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
            granted_at_event=current_version + 1,
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
