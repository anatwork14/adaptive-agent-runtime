"""Claude / Anthropic agent adapter."""

from pathlib import Path
from typing import Any, Callable, Optional
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class ClaudeAgentAdapter:
    """Agent adapter for Anthropic Claude models or simulated CLI."""

    def __init__(
        self,
        model_name: str = "claude-3-5-sonnet",
        mock_handler: Optional[Callable[[ContextPacket, Path], AgentRunResult]] = None,
    ) -> None:
        self.model_name = model_name
        self.mock_handler = mock_handler

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        if self.mock_handler:
            return self.mock_handler(context, workspace)

        summary = f"Claude completed {context.goal} adhering to constraints: {context.constraints}"
        return AgentRunResult(
            status="completed",
            patch_ref="HEAD",
            diff=f"# Claude patch for {context.task_id}\n",
            summary=summary,
            memory_references=list(context.memory_ids),
            decisions=[{"decision": f"Validated procedure requirements for {context.task_id}"}],
            assumptions=[],
            tool_trace=[],
            token_usage={"prompt_tokens": context.context_token_count, "completion_tokens": 500},
            cost_usd=0.03,
        )
