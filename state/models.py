"""Pydantic models for the Authoritative State Plane."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    DISPATCHED = "dispatched"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"
    SPLIT = "split"
    MERGED = "merged"
    FAILED = "failed"
    ABANDONED = "abandoned"
    COMPLETED = "completed"


class GateStatus(str, Enum):
    STARTED = "started"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Event(BaseModel):
    """Authoritative event record in append-only store."""

    id: int
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str
    kind: str
    project_id: str
    task_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    causation_id: Optional[int] = None
    correlation_id: Optional[str] = None
    fencing_token: Optional[int] = None
    content_hash: str

    model_config = {"frozen": True}


class ProjectState(BaseModel):
    """Materialized projection of a project's authoritative state."""

    project_id: str
    version: int = 0
    spec: Dict[str, Any] = Field(default_factory=dict)
    constraints: List[str] = Field(default_factory=list)
    active_tasks: List[str] = Field(default_factory=list)
    completed_tasks: List[str] = Field(default_factory=list)
    failed_tasks: List[str] = Field(default_factory=list)
    status: str = "active"
    created_at_event: int = 0
    updated_at_event: int = 0


class TaskState(BaseModel):
    """Materialized projection of a task in the DAG."""

    task_id: str
    project_id: str
    goal: str
    task_type: str = "code"
    required_capabilities: List[str] = Field(default_factory=list)
    risk: float = 0.5
    status: TaskStatus = TaskStatus.CREATED
    assigned_agent: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    files_declared: List[str] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    created_event: int = 0
    updated_event: int = 0
    dispatch_version: Optional[int] = None
    attempt_count: int = 0
    token_budget: int = 24000


class Lease(BaseModel):
    """Resource lease with fencing token for concurrency control."""

    resource: str
    holder: str
    fencing_token: int
    project_id: str
    task_id: Optional[str] = None
    granted_at_event: int = 0
    expires_at_event: Optional[int] = None
    is_active: bool = True


class BudgetState(BaseModel):
    """Authoritative project and task budget accounting."""

    project_id: str
    reserved_usd: float = 0.0
    consumed_usd: float = 0.0
    reserved_tokens: int = 0
    consumed_tokens: int = 0
    hard_task_ceiling_usd: float = 5.0
    hard_project_ceiling_usd: float = 500.0
    per_task_consumed_usd: Dict[str, float] = Field(default_factory=dict)
    per_task_consumed_tokens: Dict[str, int] = Field(default_factory=dict)


class PatchSubmission(BaseModel):
    """Structured patch submission from an agent.

    ``candidate_commit_sha`` is required by the integration gate for a real
    merge, but defaults to empty so non-gate utilities can still construct a
    lightweight submission. The gate rejects an empty or invalid SHA before
    integration.
    """

    patch_id: str
    task_id: str
    agent_id: str
    context_id: str
    dispatch_state_version: int
    candidate_commit_sha: str = ""
    candidate_branch: Optional[str] = None
    fencing_tokens: List[int] = Field(default_factory=list)
    diff: str = ""
    summary: str = ""
    memories_used: List[str] = Field(default_factory=list)
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    procedures: List[Dict[str, Any]] = Field(default_factory=list)
    failures: List[Dict[str, Any]] = Field(default_factory=list)


class GateResult(BaseModel):
    """Result of serial integration gate evaluation."""

    gate_run_id: str
    patch_id: str
    task_id: str
    agent_id: str
    dispatch_state_version: int
    gate_state_version: int
    status: GateStatus
    stages_passed: List[str] = Field(default_factory=list)
    rejection_stage: Optional[str] = None
    error_detail: Optional[str] = None
    staleness_score: float = 0.0
    verification_level: str = "V0"
    merged_commit_sha: Optional[str] = None
