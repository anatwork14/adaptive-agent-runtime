"""Session-aware ArcApplication specialization.

Kept separate from the core application service so autonomous execution remains
stable while ARC evolves persistent worker supervision and external review loops.
"""

from application.agents import build_agent
from application.app import ArcApplication
from application.config import AgentProfile
from application.reviews import ReviewLoopManager
from application.sessions import WorkerSessionManager


class SessionArcApplication(ArcApplication):
    """ArcApplication with persistent worker and review-loop services attached."""

    @property
    def sessions(self) -> WorkerSessionManager:
        return WorkerSessionManager(self)

    @property
    def reviews(self) -> ReviewLoopManager:
        return ReviewLoopManager(self)

    @staticmethod
    def build_agent(profile: AgentProfile):
        return build_agent(profile)
