"""OpenCode / local open-weight model adapter."""

from pathlib import Path
from typing import Callable, Optional
from adapters.base import AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class OpenCodeAgentAdapter:
    """Agent adapter for open-weights / local models (e.g. Qwen, DeepSeek)."""

    def __init__(
        self,
        model_name: str = "qwen2.5-coder-32b",
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

        return AgentRunResult(
            status="completed",
            patch_ref="HEAD",
            diff=f"# OpenCode patch for {context.task_id}\n",
            summary=f"OpenCode completed {context.goal}",
            memory_references=list(context.memory_ids),
            decisions=[],
            assumptions=[],
            tool_trace=[],
            token_usage={"prompt_tokens": context.context_token_count, "completion_tokens": 300},
            cost_usd=0.005,
        )
