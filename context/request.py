"""ContextRequest specification and Pydantic model."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ContextRequest(BaseModel):
    """Specification of what context an agent requires for a given task."""
    context_request_id: str
    project_id: str
    task_id: str
    agent_id: str
    state_version: int

    goal: str
    task_type: str = "code"
    risk: float = 0.5

    files_declared: List[str] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)

    token_budget: int = 24000
    agent_context_limit: int = 128000

    requested_classes: List[str] = Field(
        default_factory=lambda: [
            "decision",
            "assumption",
            "failure",
            "procedure",
            "code_surface",
        ]
    )
