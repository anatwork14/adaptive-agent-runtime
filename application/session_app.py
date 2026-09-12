"""Session-aware ArcApplication specialization.

Kept separate from the core application service so the v0.5 execution surface
remains stable while v0.6 evolves persistent worker supervision.
"""

from application.agents import build_agent
from application.app import ArcApplication
from application.config import AgentProfile
from application.sessions import WorkerSessionManager


class SessionArcApplication(ArcApplication):
    """ArcApplication with persistent worker-session services attached."""

    @property
    def sessions(self) -> WorkerSessionManager:
        return WorkerSessionManager(self)

    @staticmethod
    def build_agent(profile: AgentProfile):
        return build_agent(profile)
