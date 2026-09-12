"""External integration adapters for ARC.

Integrations project external systems into ARC events. They never replace the
append-only ARC event log or Git as authoritative project state.
"""

from integrations.github_cli import GitHubCliClient, GitHubPullRequestSnapshot

__all__ = ["GitHubCliClient", "GitHubPullRequestSnapshot"]
