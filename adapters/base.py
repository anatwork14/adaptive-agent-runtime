"""Agent Adapter interface and run result definitions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from context.compiler import ContextPacket


class AgentBudget(BaseModel):
    max_usd: float = 5.0
    max_tokens: int = 24000
    timeout_seconds: int = 180


class AgentRunResult(BaseModel):
    status: str = "completed"  # completed | failed | cancelled | budget_exhausted
    patch_ref: str = ""
    diff: str = ""
    summary: str = ""
    memory_references: List[str] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    tool_trace: List[Dict[str, Any]] = Field(default_factory=list)
    token_usage: Dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0


class AgentAdapter(Protocol):
    """Protocol for model and CLI agent adapters."""

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        ...
