"""Baseline B3: Static structured handoff packet without adaptive memory plane."""

from pathlib import Path
from typing import Dict, List, Optional
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket
from state.models import TaskState


class BaselineB3StaticStructured:
    """Delivers static structured handoff packets containing only task core and visible repo files."""

    def __init__(self, agent: AgentAdapter) -> None:
        self.agent = agent

    async def execute(
        self,
        task: TaskState,
        workspace: Path,
        constraints: Optional[List[str]] = None,
        budget_usd: float = 3.0,
    ) -> AgentRunResult:
        context = ContextPacket(
            context_id=f"CTX_B3_{task.task_id}",
            project_id=task.project_id,
            task_id=task.task_id,
            agent_id="static_agent",
            state_version=1,
            compiled_event=1,
            goal=task.goal,
            acceptance_criteria=task.acceptance_criteria,
            constraints=constraints or [],
            code_context=[{"path": f} for f in task.files_declared],
            # Note: Explicitly NO long-term memory, decisions, procedures, or failure history
            decisions=[],
            assumptions=[],
            failures=[],
            procedures=[],
            token_budget=task.token_budget,
            context_token_count=1500,
            digest=f"sha256:b3_{task.task_id}",
        )
        budget = AgentBudget(max_usd=budget_usd, max_tokens=task.token_budget)
        return await self.agent.run(context=context, workspace=workspace, budget=budget)
