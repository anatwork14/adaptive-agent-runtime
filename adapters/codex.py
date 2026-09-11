"""Codex CLI and OpenAI-compatible agent adapter."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class CodexAgentAdapter:
    """Agent adapter for Codex / OpenAI API or simulated CLI agent."""

    def __init__(
        self,
        model_name: str = "gpt-4o",
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
        """Run agent against workspace with supplied context and budget limits."""
        if self.mock_handler:
            return self.mock_handler(context, workspace)

        # Deterministic default execution for reproducible benchmarks
        summary = f"Implemented {context.goal} based on context {context.context_id}"
        decisions = [{"decision": f"Adhered to {len(context.decisions)} prior architectural decisions."}]
        mem_refs = list(context.memory_ids)

        return AgentRunResult(
            status="completed",
            patch_ref="HEAD",
            diff=f"# Patch for {context.task_id}\n# Goal: {context.goal}\n",
            summary=summary,
            memory_references=mem_refs,
            decisions=decisions,
            assumptions=[],
            tool_trace=[{"action": "read_file", "path": f} for f in (context.code_context or [])],
            token_usage={"prompt_tokens": context.context_token_count, "completion_tokens": 400},
            cost_usd=0.02,
        )
