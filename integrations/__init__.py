"""External integration adapters for ARC.

Integrations project external systems into ARC events. They never replace the
append-only ARC event log or Git as authoritative project state.
"""

from integrations.agent_bridge import (
    AgentBridgeClient,
    BridgeDagRunProjection,
    BridgeIntegrationCapabilities,
    BridgeIntegrationEvent,
    BridgeIntegrationError,
)
from integrations.github_cli import GitHubCliClient, GitHubPullRequestSnapshot

__all__ = [
    "AgentBridgeClient",
    "BridgeDagRunProjection",
    "BridgeIntegrationCapabilities",
    "BridgeIntegrationEvent",
    "BridgeIntegrationError",
    "GitHubCliClient",
    "GitHubPullRequestSnapshot",
]
