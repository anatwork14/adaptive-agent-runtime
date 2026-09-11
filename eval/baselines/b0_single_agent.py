"""Baseline B0: Single agent, full uninterrupted session."""

from pathlib import Path
from typing import Dict
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class BaselineB0SingleAgent:
    """Runs a single agent with full session context without multi-agent handoff."""

    def __init__(self, agent: AgentAdapter) -> None:
        self.agent = agent

    async def execute(self, goal: str, workspace: Path, budget_usd: float = 5.0) -> AgentRunResult:
        context = ContextPacket(
            context_id="CTX_B0_FULL",
            project_id="b0_eval",
            task_id="T_FULL",
            agent_id="single_agent",
            state_version=1,
            compiled_event=1,
            goal=goal,
            constraints=[],
            token_budget=32000,
            context_token_count=1000,
            digest="sha256:b0",
        )
        budget = AgentBudget(max_usd=budget_usd, max_tokens=32000)
        return await self.agent.run(context=context, workspace=workspace, budget=budget)
