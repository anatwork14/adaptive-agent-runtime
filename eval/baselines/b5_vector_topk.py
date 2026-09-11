"""Baseline B5: Vector top-k memory retrieval without versioning or supersession awareness."""

from pathlib import Path
from typing import Dict, List
from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextPacket
from indexes.vector import VectorIndex
from state.models import TaskState


class BaselineB5VectorTopK:
    """Uses standard non-versioned vector search to retrieve top-k memory chunks."""

    def __init__(self, agent: AgentAdapter, vector_index: VectorIndex, memory_docs: Dict[str, str]) -> None:
        self.agent = agent
        self.vector_index = vector_index
        self.memory_docs = memory_docs

    async def execute(self, task: TaskState, workspace: Path, top_k: int = 5) -> AgentRunResult:
        query_vec = VectorIndex.mock_embed_text(task.goal)
        top_hits = self.vector_index.search(query_vec, top_k=top_k)

        retrieved_decisions = []
        for mem_id, sim in top_hits:
            text = self.memory_docs.get(mem_id, "")
            retrieved_decisions.append({"memory_id": mem_id, "text": text, "similarity": sim})

        context = ContextPacket(
            context_id=f"CTX_B5_{task.task_id}",
            project_id=task.project_id,
            task_id=task.task_id,
            agent_id="vector_agent",
            state_version=1,
            compiled_event=1,
            goal=task.goal,
            decisions=retrieved_decisions,
            token_budget=task.token_budget,
            context_token_count=len(retrieved_decisions) * 50 + 1000,
            digest=f"sha256:b5_{task.task_id}",
        )
        budget = AgentBudget(max_usd=3.0, max_tokens=task.token_budget)
        return await self.agent.run(context=context, workspace=workspace, budget=budget)
