"""Baseline B2: Static multi-agent transcript handoff passing full conversational history."""

from pathlib import Path
from typing import List
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket


class BaselineB2TranscriptHandoff:
    """Passes raw concatenated conversational transcripts between sequential agents."""

    def __init__(self, agents: List[AgentAdapter]) -> None:
        self.agents = agents
        self.transcript_history: List[str] = []

    async def execute_step(
        self,
        agent_idx: int,
        task_goal: str,
        workspace: Path,
        budget_usd: float = 2.5,
    ) -> AgentRunResult:
        agent = self.agents[agent_idx % len(self.agents)]
        transcript_dump = "\n---\n".join(self.transcript_history)

        context = ContextPacket(
            context_id=f"CTX_B2_STEP_{agent_idx}",
            project_id="b2_eval",
            task_id=f"T_{agent_idx}",
            agent_id=f"agent_{agent_idx}",
            state_version=agent_idx + 1,
            compiled_event=agent_idx + 1,
            goal=task_goal + f"\n\nPrior Transcript History:\n{transcript_dump}",
            constraints=[],
            token_budget=32000,
            context_token_count=len(transcript_dump) // 4 + 500,
            digest=f"sha256:b2_{agent_idx}",
        )

        budget = AgentBudget(max_usd=budget_usd, max_tokens=32000)
        res = await agent.run(context=context, workspace=workspace, budget=budget)
        self.transcript_history.append(f"Agent {agent_idx} Output:\n{res.summary}\nDiff:\n{res.diff}")
        return res
