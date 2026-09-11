"""Google Antigravity CLI coding-agent adapter."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from adapters.base import AgentBudget, AgentRunResult
from adapters.cli_process import AgentAdapterUnavailable, render_context_prompt
from context.compiler import ContextPacket


class AntigravityAgentAdapter:
    """Run Antigravity (`agy`) in non-interactive print mode.

    Antigravity accepts its prompt as an argument via ``agy -p`` rather than
    ARC's normal stdin contract, so this adapter owns the small provider-specific
    invocation while ARC still measures the actual git changes afterwards.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.name = "Antigravity"
        self.model_name = model_name

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        if shutil.which("agy") is None:
            raise AgentAdapterUnavailable(
                "Antigravity CLI executable 'agy' was not found. Install and authenticate agy first."
            )

        prompt = render_context_prompt(context)
        command = ["agy", "-p", prompt]
        if self.model_name:
            command.extend(["--model", self.model_name])

        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=budget.timeout_seconds
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return AgentRunResult(
                status="failed",
                summary=f"Antigravity timed out after {budget.timeout_seconds}s",
                tool_trace=[{"action": "cli_timeout", "command": ["agy", "-p", "<ARC_CONTEXT>"]}],
            )

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            return AgentRunResult(
                status="failed",
                summary=f"Antigravity exited with code {process.returncode}: {err[-4000:]}",
                tool_trace=[{"action": "cli_run", "command": ["agy", "-p", "<ARC_CONTEXT>"], "returncode": process.returncode}],
            )

        return AgentRunResult(
            status="completed",
            patch_ref="WORKTREE",
            summary=out[-8000:] or "Antigravity completed without textual output",
            memory_references=list(context.memory_ids),
            tool_trace=[{"action": "cli_run", "command": ["agy", "-p", "<ARC_CONTEXT>"], "returncode": process.returncode}],
            token_usage={},
            cost_usd=0.0,
        )
