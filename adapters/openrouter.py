"""OpenRouter adapter boundary.

OpenRouter exposes model inference, not a repository-editing coding-agent runtime
by itself. ARC therefore refuses to pretend that a text completion is a real
workspace patch. Use OpenRouter behind an actual tool-using agent command, or
implement a dedicated tool loop before enabling this adapter for execution.
"""

from pathlib import Path

from adapters.base import AgentBudget, AgentRunResult
from adapters.cli_process import AgentAdapterUnavailable
from context.compiler import ContextPacket


class OpenRouterAgentAdapter:
    """Explicitly unsupported as a direct workspace executor for now."""

    def __init__(self, model_name: str = "openai/gpt-4o-mini") -> None:
        self.model_name = model_name

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        raise AgentAdapterUnavailable(
            "OpenRouter is a model gateway, not a filesystem coding-agent runtime. "
            "ARC previously returned a fake textual diff here. Configure a real "
            "tool-using agent/CLI that uses OpenRouter, then wrap it with "
            "SubprocessCodingAgent instead."
        )
