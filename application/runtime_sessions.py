"""WorkerSessionManager variant that owns live-runtime cleanup boundaries."""

from __future__ import annotations

from state.models import GateResult

from application.sessions import WorkerSession, WorkerSessionManager


class RuntimeWorkerSessionManager(WorkerSessionManager):
    """Stop tmux-owned runtimes before a worker worktree can disappear."""

    def _stop_live_runtimes(self, session_id: str) -> None:
        # Runtime stop is operational cleanup, not a correctness decision. If a
        # tmux session already exited, stop_* is idempotent and simply projects
        # the current non-running state.
        self.app.worker_runtime.stop_preview(session_id)
        self.app.worker_runtime.stop_terminal(session_id)

    async def submit(self, session_id: str) -> GateResult:
        self._stop_live_runtimes(session_id)
        return await super().submit(session_id)

    def stop(self, session_id: str, *, reason: str = "operator stopped worker") -> WorkerSession:
        self._stop_live_runtimes(session_id)
        return super().stop(session_id, reason=reason)
