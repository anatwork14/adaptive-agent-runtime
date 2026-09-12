"""Operational supervisor for cancellable Workspace provider turns.

Live provider processes are intentionally not authoritative ARC state. This
supervisor owns only in-process asyncio task/cancellation handles while durable
turn lifecycle/output remains in the ARC event log and draft state remains in
the worker worktree.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Callable
from typing import Any

from application.session_app import SessionArcApplication
from application.sessions import SessionStatus


class LiveTurnSupervisor:
    """Own active browser-started turns without making process state durable."""

    def __init__(
        self,
        *,
        open_arc: Callable[[], SessionArcApplication],
        session_locks: dict[str, asyncio.Lock],
    ) -> None:
        self._open_arc = open_arc
        self._session_locks = session_locks
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._turn_ids: dict[str, str] = {}
        self._errors: dict[str, str] = {}
        self._cancel_requested: set[str] = set()

    def state(self, session_id: str) -> dict[str, Any]:
        task = self._tasks.get(session_id)
        return {
            "session_id": session_id,
            "turn_id": self._turn_ids.get(session_id),
            "active": bool(task and not task.done()),
            "done": bool(task and task.done()),
            "cancel_requested": session_id in self._cancel_requested,
            "error": self._errors.get(session_id),
        }

    def active(self, session_id: str) -> bool:
        task = self._tasks.get(session_id)
        return bool(task and not task.done())

    def _validate_session(self, session_id: str) -> None:
        with self._open_arc() as arc:
            session = arc.sessions.get(session_id)
            if not session:
                raise ValueError(f"Worker session {session_id} not found")
            if session.status not in arc.sessions.ACTIVE:
                raise ValueError(
                    f"Session {session_id} is {session.status.value}; it is not interactive"
                )
            if session.status == SessionStatus.RUNNING and not self.active(session_id):
                raise ValueError(
                    f"Session {session_id} is marked running from a previous supervisor. "
                    "Resume the worker before starting a new live turn."
                )

    async def start(self, session_id: str, instruction: str) -> dict[str, Any]:
        if not instruction.strip():
            raise ValueError("Instruction cannot be empty")
        if self.active(session_id):
            raise RuntimeError("worker is already processing a live turn")
        self._validate_session(session_id)

        lock = self._session_locks[session_id]
        if lock.locked():
            raise RuntimeError("worker is already processing an action")

        # Acquire before returning from the API so every other action route sees
        # the worker as busy immediately; this avoids a scheduling race between
        # create_task() and the background runner entering the lock.
        await lock.acquire()
        turn_id = f"TURN_{uuid.uuid4().hex[:10]}"
        cancel_event = asyncio.Event()
        self._turn_ids[session_id] = turn_id
        self._cancel_events[session_id] = cancel_event
        self._errors.pop(session_id, None)
        self._cancel_requested.discard(session_id)

        async def run() -> None:
            arc = self._open_arc()
            try:
                await arc.sessions.send(
                    session_id,
                    instruction,
                    turn_id=turn_id,
                    cancel_event=cancel_event,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # session.send records authoritative failure event
                self._errors[session_id] = str(exc)
            finally:
                arc.close()
                if lock.locked():
                    lock.release()

        try:
            self._tasks[session_id] = asyncio.create_task(
                run(), name=f"arc-live-turn-{session_id}-{turn_id}"
            )
        except Exception:
            lock.release()
            self._cancel_events.pop(session_id, None)
            self._turn_ids.pop(session_id, None)
            raise
        return self.state(session_id)

    def _record_cancel_request(self, session_id: str, turn_id: str | None) -> None:
        if session_id in self._cancel_requested:
            return
        with self._open_arc() as arc:
            session = arc.sessions.get(session_id)
            if not session:
                return
            arc.event_store.append(
                actor="operator",
                kind="session.turn_cancel_requested",
                project_id=arc.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={"session_id": session_id, "turn_id": turn_id},
            )
        self._cancel_requested.add(session_id)

    async def cancel(
        self,
        session_id: str,
        *,
        wait: bool = False,
        timeout_seconds: float = 6.0,
    ) -> dict[str, Any]:
        task = self._tasks.get(session_id)
        if not task or task.done():
            return self.state(session_id)

        turn_id = self._turn_ids.get(session_id)
        self._record_cancel_request(session_id, turn_id)
        event = self._cancel_events.get(session_id)
        if event is not None:
            event.set()

        if wait:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                # Last-resort supervisor cancellation. SubprocessCodingAgent
                # catches task cancellation and terminates its child process.
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        return self.state(session_id)

    async def cancel_all(self) -> None:
        active = [session_id for session_id in self._tasks if self.active(session_id)]
        await asyncio.gather(
            *(self.cancel(session_id, wait=True) for session_id in active),
            return_exceptions=True,
        )
