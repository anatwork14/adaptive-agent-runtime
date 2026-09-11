"""Context Compiler assembling immutable, token-budgeted ContextPackets."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from context.allocator import BudgetAllocator, ClassBudgets
from context.digest import compute_context_digest
from context.ranking import CandidateRanker
from context.request import ContextRequest
from context.retrieval import MemoryRetriever, RetrievalResult
from memory.models import Memory, MemoryStatus, MemoryType
from state.events import EventStore
from state.models import ProjectState, TaskState


class ContextPacket(BaseModel):
    """Immutable compiled context packet dispatched to an agent."""
    context_id: str
    project_id: str
    task_id: str
    agent_id: str

    state_version: int
    compiled_event: int

    goal: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    dependency_state: List[Dict[str, Any]] = Field(default_factory=list)

    decisions: List[Dict[str, Any]] = Field(default_factory=list)
    assumptions: List[Dict[str, Any]] = Field(default_factory=list)
    code_context: List[Dict[str, Any]] = Field(default_factory=list)
    failures: List[Dict[str, Any]] = Field(default_factory=list)
    procedures: List[Dict[str, Any]] = Field(default_factory=list)
    open_questions: List[Dict[str, Any]] = Field(default_factory=list)

    leases: List[Dict[str, Any]] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)

    budget_remaining_tokens: int = 0
    context_token_count: int = 0
    memory_ids: List[str] = Field(default_factory=list)
    digest: str = ""

    model_config = {"frozen": True}


class ContextCompiler:
    """Compiles retrieved authoritative and derived state into the smallest sufficient immutable packet."""

    def __init__(
        self,
        event_store: EventStore,
        allocator: Optional[BudgetAllocator] = None,
    ) -> None:
        self.event_store = event_store
        self.allocator = allocator or BudgetAllocator()

    def compile(
        self,
        request: ContextRequest,
        retrieval: RetrievalResult,
        project_state: ProjectState,
        task_state: Optional[TaskState] = None,
        active_leases: Optional[List[Dict[str, Any]]] = None,
    ) -> ContextPacket:
        """Execute Context Compilation Algorithm (Section 34)."""
        current_event = self.event_store.current_version(request.project_id)
        context_id = f"CTX_{uuid.uuid4().hex[:8]}"

        # 1. Budget allocation by class (Sections 25 & 26)
        budgets: ClassBudgets = self.allocator.allocate(
            risk=request.risk,
            declared_budget=request.token_budget,
        )

        # 2. C0 Authoritative Core (never omitted, Invariant AC4)
        goal = request.goal
        acceptance_criteria = task_state.acceptance_criteria if task_state else []
        constraints = list(project_state.constraints)
        leases = active_leases or []
        dependency_state = [{"task_id": dep, "status": "completed"} for dep in request.dependencies]

        # 3. Partition retrieved memories by class and enforce class budgets
        decisions: List[Dict[str, Any]] = []
        assumptions: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        procedures: List[Dict[str, Any]] = []
        memory_ids: List[str] = []

        tokens_used_decisions = 0
        tokens_used_assumptions = 0
        tokens_used_failures = 0
        tokens_used_procedures = 0

        for cand in retrieval.candidates:
            mem = cand.memory

            # Strict supersession / expiration check (Invariant AC3)
            if mem.status == MemoryStatus.SUPERSEDED:
                continue
            if mem.status in (MemoryStatus.DELETED, MemoryStatus.ARCHIVED):
                continue
            if mem.valid_from_event > request.state_version:
                continue
            if mem.valid_to_event is not None and mem.valid_to_event < request.state_version:
                continue

            cost = max(10, mem.token_size)

            if mem.type in (MemoryType.DECISION, MemoryType.CONSTRAINT, MemoryType.FACT):
                if tokens_used_decisions + cost <= budgets.c1_decisions:
                    decisions.append({
                        "memory_id": mem.memory_id,
                        "text": mem.content_text,
                        "source_events": mem.source_events,
                    })
                    tokens_used_decisions += cost
                    memory_ids.append(mem.memory_id)

            elif mem.type == MemoryType.ASSUMPTION:
                if tokens_used_assumptions + cost <= budgets.c3_assumptions:
                    assumptions.append({
                        "memory_id": mem.memory_id,
                        "text": mem.content_text,
                        "confidence": mem.confidence,
                        "status": mem.status.value,
                    })
                    tokens_used_assumptions += cost
                    memory_ids.append(mem.memory_id)

            elif mem.type == MemoryType.FAILURE:
                if tokens_used_failures + cost <= budgets.c4_failures:
                    failures.append({
                        "memory_id": mem.memory_id,
                        "text": mem.content_text,
                        "source_events": mem.source_events,
                    })
                    tokens_used_failures += cost
                    memory_ids.append(mem.memory_id)

            elif mem.type == MemoryType.PROCEDURE:
                if tokens_used_procedures + cost <= budgets.c5_procedures:
                    procedures.append({
                        "memory_id": mem.memory_id,
                        "text": mem.content_text,
                        "source_events": mem.source_events,
                    })
                    tokens_used_procedures += cost
                    memory_ids.append(mem.memory_id)

        # 4. Code Evidence (C2)
        code_context: List[Dict[str, Any]] = []
        tokens_used_code = 0
        for fpath in request.files_declared:
            item = {"path": fpath, "symbols": request.symbols}
            cost = 100
            if tokens_used_code + cost <= budgets.c2_code:
                code_context.append(item)
                tokens_used_code += cost

        # Compute total context token count
        authoritative_tokens = BudgetAllocator.estimate_tokens(goal + " ".join(constraints) + " ".join(acceptance_criteria))
        total_tokens = (
            authoritative_tokens
            + tokens_used_decisions
            + tokens_used_assumptions
            + tokens_used_failures
            + tokens_used_procedures
            + tokens_used_code
        )

        remaining_budget = max(0, request.token_budget - total_tokens)

        # Risk flags
        risk_flags = []
        if request.risk > 0.7:
            risk_flags.append("HIGH_RISK_TASK")
        if any(a.get("status") == "disputed" for a in assumptions):
            risk_flags.append("CONTRADICTORY_ASSUMPTIONS_PRESENT")

        packet_dict = {
            "context_id": context_id,
            "project_id": request.project_id,
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "state_version": request.state_version,
            "compiled_event": current_event,
            "goal": goal,
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "dependency_state": dependency_state,
            "decisions": decisions,
            "assumptions": assumptions,
            "code_context": code_context,
            "failures": failures,
            "procedures": procedures,
            "open_questions": [],
            "leases": leases,
            "risk_flags": risk_flags,
            "budget_remaining_tokens": remaining_budget,
            "context_token_count": total_tokens,
            "memory_ids": sorted(list(set(memory_ids))),
        }

        # Canonical digest (Section 28)
        digest = compute_context_digest(packet_dict)
        packet_dict["digest"] = digest

        # Invariant I8: Append context.compiled event
        self.event_store.append(
            actor="orchestrator",
            kind="context.compiled",
            project_id=request.project_id,
            task_id=request.task_id,
            payload={
                "context_id": context_id,
                "state_version": request.state_version,
                "digest": digest,
                "token_count": total_tokens,
                "memory_ids": memory_ids,
            },
        )

        return ContextPacket(**packet_dict)
