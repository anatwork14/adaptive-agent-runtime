"""Agent adapters package."""

from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from adapters.claude import ClaudeAgentAdapter
from adapters.codex import CodexAgentAdapter
from adapters.opencode import OpenCodeAgentAdapter
from adapters.openrouter import OpenRouterAgentAdapter

__all__ = [
    "AgentAdapter",
    "AgentBudget",
    "AgentRunResult",
    "CodexAgentAdapter",
    "ClaudeAgentAdapter",
    "OpenCodeAgentAdapter",
    "OpenRouterAgentAdapter",
]
