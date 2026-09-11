"""Deterministic mock adapter used only by tests and local dry-runs."""

from pathlib import Path
from typing import Callable, Optional

from adapters.base import AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class MockAgentAdapter:
    """A deterministic test double that writes a real repository change.

    Real provider adapters must never silently fall back to this behavior. Tests
    that need a simulated agent should import ``MockAgentAdapter`` explicitly.
    """

    def __init__(
        self,
        name: str = "mock",
        handler: Optional[Callable[[ContextPacket, Path], AgentRunResult]] = None,
    ) -> None:
        self.name = name
        self.handler = handler

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        if self.handler:
            return self.handler(context, workspace)

        raw_path = ""
        if context.files_declared:
            raw_path = str(context.files_declared[0])
        elif context.code_context:
            raw_path = str(context.code_context[0].get("path", ""))

        if raw_path and not any(ch in raw_path for ch in "*?[]") and not Path(raw_path).is_absolute():
            target = workspace / raw_path
        else:
            target = workspace / ".arc-mock" / f"{context.task_id}.txt"

        target.parent.mkdir(parents=True, exist_ok=True)
        previous = target.read_text(encoding="utf-8") if target.exists() else ""
        target.write_text(
            previous
            + f"\n# ARC mock agent: {self.name}\n"
            + f"# task={context.task_id}\n"
            + f"# goal={context.goal}\n",
            encoding="utf-8",
        )

        return AgentRunResult(
            status="completed",
            patch_ref="WORKTREE",
            diff="",
            summary=f"Mock agent {self.name} completed {context.goal}",
            memory_references=list(context.memory_ids),
            decisions=[],
            assumptions=[],
            tool_trace=[{"action": "write_file", "path": str(target.relative_to(workspace))}],
            token_usage={"prompt_tokens": context.context_token_count, "completion_tokens": 64},
            cost_usd=0.0,
        )
