"""Polling event subscription used by CLI watch, TUI, and future APIs."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List

from state.events import EventStore
from state.models import Event


class EventStream:
    """Read authoritative events incrementally without adding another source of truth."""

    def __init__(self, store: EventStore, project_id: str) -> None:
        self.store = store
        self.project_id = project_id

    def poll(self, after_event_id: int, *, limit: int = 100) -> List[Event]:
        return self.store.read_after(after_event_id, project_id=self.project_id, limit=limit)

    async def subscribe(
        self,
        *,
        after_event_id: int = 0,
        poll_interval: float = 0.35,
    ) -> AsyncIterator[Event]:
        """Yield new events in ID order using SQLite as the authoritative transport."""
        cursor = after_event_id
        while True:
            events = self.poll(cursor)
            if events:
                for event in events:
                    cursor = event.id
                    yield event
                continue
            await asyncio.sleep(poll_interval)
