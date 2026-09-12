"""Session-aware ArcApplication specialization.

Kept separate from the core application service so autonomous execution remains
stable while ARC evolves persistent worker supervision, external review loops,
and optional live runtime supervision.
"""

from pathlib import Path

from application.agents import build_agent
from application.app import ArcApplication
from application.config import AgentProfile
from application.reviews import ReviewLoopManager
from application.runtime_sessions import RuntimeWorkerSessionManager
from application.worker_runtime import WorkerRuntimeManager


class SessionArcApplication(ArcApplication):
    """ArcApplication with persistent worker/review/runtime services attached."""

    @property
    def repo_path(self) -> Path:
        """Compatibility alias used by integration services."""
        return self.repo

    @property
    def sessions(self) -> RuntimeWorkerSessionManager:
        return RuntimeWorkerSessionManager(self)

    @property
    def reviews(self) -> ReviewLoopManager:
        return ReviewLoopManager(self)

    @property
    def worker_runtime(self) -> WorkerRuntimeManager:
        return WorkerRuntimeManager(self)

    @staticmethod
    def build_agent(profile: AgentProfile):
        return build_agent(profile)
