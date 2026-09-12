"""Context compiler assembling immutable, token-budgeted ContextPackets."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field

from context.allocator import BudgetAllocator, ClassBudgets
from context.digest import compute_context_digest
from context.request import ContextRequest
from context.retrieval import RetrievalResult
from memory.models import MemoryStatus, MemoryType
from state.events import EventStore
from state.models import ProjectState, TaskState


class ContextBudgetExceeded(ValueError):
    """Raised when mandatory authoritative context exceeds the hard budget."""


class ContextPacket(BaseModel):
    """Immutable compiled context packet dispatched to an agent."""

    context_id: str
    project_id: str
    task_id: str
    agent_id: str
    state_version: int
    compiled_event: int
    context_policy: str = "B7"
    goal: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    dependency_state: List[Dict[str, Any]] = Field(default_factory=list)
    files_declared: List[str] = Field(default_factory=list)
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
    stale_memory_ids: List[str] = Field(default_factory=list)
    retrieval_strategies: List[str] = Field(default_factory=list)
    digest: str = ""

    model_config = {"frozen": True}


class ContextCompiler:
    """Compile authoritative state + selected memory into bounded task context."""

    def __init__(
        self,
        event_store: EventStore,
        allocator: Optional[BudgetAllocator] = None,
        repo_path: Optional[str | Path] = None,
    ) -> None:
        self.event_store = event_store
        self.allocator = allocator or BudgetAllocator()
        self.repo_path = Path(repo_path).resolve() if repo_path is not None else None

    def _declared_files(self, patterns: Iterable[str]) -> List[Path]:
        """Resolve declared paths/globs without allowing repository escape."""
        if self.repo_path is None:
            return []

        seen: set[Path] = set()
        results: List[Path] = []
        for raw in patterns:
            if not raw or Path(raw).is_absolute():
                continue
            has_glob = any(ch in raw for ch in "*?[]")
            candidates = self.repo_path.glob(raw) if has_glob else [self.repo_path / raw]
            for candidate in candidates:
                try:
                    resolved = candidate.resolve()
                    resolved.relative_to(self.repo_path)
                except (OSError, ValueError):
                    continue
                if not resolved.is_file():
                    continue
                rel = resolved.relative_to(self.repo_path)
                if any(part in {".git", ".arc", ".venv", "__pycache__"} for part in rel.parts):
                    continue
                if resolved not in seen:
                    seen.add(resolved)
                    results.append(resolved)
        return sorted(results, key=lambda path: str(path.relative_to(self.repo_path)))

    def _code_evidence(
        self,
        patterns: Iterable[str],
        symbols: List[str],
        token_budget: int,
    ) -> tuple[List[Dict[str, Any]], int]:
        if self.repo_path is None or token_budget <= 0:
            return [], 0

        evidence: List[Dict[str, Any]] = []
        used = 0
        for path in self._declared_files(patterns):
            if used >= token_budget:
                break
            try:
                full_content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            remaining = token_budget - used
            if remaining <= 0:
                break
            max_chars = max(0, remaining * 4)
            included = full_content[:max_chars]
            cost = self.allocator.estimate_tokens(included)
            if cost > remaining:
                continue

            rel = str(path.relative_to(self.repo_path))
            evidence.append(
                {
                    "path": rel,
                    "start_line": 1,
                    "end_line": max(1, included.count("\n") + 1),
                    "content": included,
                    "content_hash": hashlib.sha256(
                        full_content.encode("utf-8")
                    ).hexdigest(),
                    "truncated": len(included) < len(full_content),
                    "symbols_requested": list(symbols),
                    "reason": "declared task code surface",
                }
            )
            used += cost
        return evidence, used

    @staticmethod
    def _memory_is_stale(memory, state_version: int) -> bool:
        if memory.status in (
            MemoryStatus.SUPERSEDED,
            MemoryStatus.DELETED,
            MemoryStatus.ARCHIVED,
        ):
            return True
        if memory.valid_from_event > state_version:
            return True
        return memory.valid_to_event is not None and memory.valid_to_event < state_version

    def compile(
        self,
        request: ContextRequest,
        retrieval: RetrievalResult,
        project_state: ProjectState,
        task_state: Optional[TaskState] = None,
        active_leases: Optional[List[Dict[str, Any]]] = None,
        *,
        policy_id: str = "B7",
        enforce_memory_validity: bool = True,
    ) -> ContextPacket:
        """Compile context while enforcing ``request.token_budget`` as a hard ceiling.

        ``enforce_memory_validity`` defaults to the safe production behavior. It
        exists so research baselines can intentionally deliver stale/superseded
        memory while still sharing the exact same packet assembly and execution
        path. Production callers should not disable it.
        """
        context_id = f"CTX_{uuid.uuid4().hex[:8]}"
        budgets: ClassBudgets = self.allocator.allocate(
            risk=request.risk,
            declared_budget=request.token_budget,
        )

        goal = request.goal
        acceptance_criteria = task_state.acceptance_criteria if task_state else []
        constraints = list(project_state.constraints)
        leases = active_leases or []
        dependency_state = [
            {"task_id": dependency, "status": "dependency"}
            for dependency in request.dependencies
        ]

        authoritative_text = "\n".join(
            [
                goal,
                *acceptance_criteria,
                *constraints,
                *request.dependencies,
                *request.files_declared,
            ]
        )
        authoritative_tokens = self.allocator.estimate_tokens(authoritative_text)
        if authoritative_tokens > budgets.total_budget:
            raise ContextBudgetExceeded(
                f"mandatory authoritative context ({authoritative_tokens} tokens) "
                f"exceeds hard budget ({budgets.total_budget})"
            )
        remaining_total = budgets.total_budget - authoritative_tokens

        decisions: List[Dict[str, Any]] = []
        assumptions: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []
        procedures: List[Dict[str, Any]] = []
        memory_ids: List[str] = []
        stale_memory_ids: List[str] = []

        class_used = {
            "decisions": 0,
            "assumptions": 0,
            "failures": 0,
            "procedures": 0,
        }
        class_caps = {
            "decisions": budgets.c1_decisions,
            "assumptions": budgets.c3_assumptions,
            "failures": budgets.c4_failures,
            "procedures": budgets.c5_procedures,
        }

        for candidate in retrieval.candidates:
            memory = candidate.memory
            is_stale = self._memory_is_stale(memory, request.state_version)
            if is_stale and enforce_memory_validity:
                continue

            cost = max(
                1,
                memory.token_size
                or self.allocator.estimate_tokens(memory.content_text),
            )
            bucket: Optional[str] = None
            target: Optional[List[Dict[str, Any]]] = None
            entry: Dict[str, Any]

            if memory.type in (
                MemoryType.DECISION,
                MemoryType.CONSTRAINT,
                MemoryType.FACT,
            ):
                bucket, target = "decisions", decisions
                entry = {
                    "memory_id": memory.memory_id,
                    "text": memory.content_text,
                    "source_events": memory.source_events,
                    "valid_from_event": memory.valid_from_event,
                    "valid_to_event": memory.valid_to_event,
                    "status": memory.status.value,
                }
            elif memory.type == MemoryType.ASSUMPTION:
                bucket, target = "assumptions", assumptions
                entry = {
                    "memory_id": memory.memory_id,
                    "text": memory.content_text,
                    "confidence": memory.confidence,
                    "status": memory.status.value,
                    "source_events": memory.source_events,
                }
            elif memory.type == MemoryType.FAILURE:
                bucket, target = "failures", failures
                entry = {
                    "memory_id": memory.memory_id,
                    "text": memory.content_text,
                    "status": memory.status.value,
                    "source_events": memory.source_events,
                }
            elif memory.type == MemoryType.PROCEDURE:
                bucket, target = "procedures", procedures
                entry = {
                    "memory_id": memory.memory_id,
                    "text": memory.content_text,
                    "status": memory.status.value,
                    "source_events": memory.source_events,
                }
            else:
                continue

            assert bucket is not None and target is not None
            if class_used[bucket] + cost > class_caps[bucket] or cost > remaining_total:
                continue
            target.append(entry)
            class_used[bucket] += cost
            remaining_total -= cost
            memory_ids.append(memory.memory_id)
            if is_stale:
                stale_memory_ids.append(memory.memory_id)

        code_cap = min(budgets.c2_code, remaining_total)
        code_context, code_tokens = self._code_evidence(
            request.files_declared,
            request.symbols,
            code_cap,
        )
        remaining_total -= code_tokens

        total_tokens = budgets.total_budget - remaining_total
        if total_tokens > request.token_budget:
            raise AssertionError("compiled context exceeded the declared hard budget")

        risk_flags: List[str] = []
        if request.risk > 0.7:
            risk_flags.append("HIGH_RISK_TASK")
        if any(item.get("status") == "disputed" for item in assumptions):
            risk_flags.append("CONTRADICTORY_ASSUMPTIONS_PRESENT")
        if stale_memory_ids:
            risk_flags.append("STALE_MEMORY_DELIVERED")
        if self.repo_path is None and request.files_declared:
            risk_flags.append("CODE_EVIDENCE_UNAVAILABLE")

        packet_dict: Dict[str, Any] = {
            "context_id": context_id,
            "project_id": request.project_id,
            "task_id": request.task_id,
            "agent_id": request.agent_id,
            "state_version": request.state_version,
            "compiled_event": self.event_store.current_version(request.project_id),
            "context_policy": policy_id,
            "goal": goal,
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "dependency_state": dependency_state,
            "files_declared": list(request.files_declared),
            "decisions": decisions,
            "assumptions": assumptions,
            "code_context": code_context,
            "failures": failures,
            "procedures": procedures,
            "open_questions": [],
            "leases": leases,
            "risk_flags": risk_flags,
            "budget_remaining_tokens": remaining_total,
            "context_token_count": total_tokens,
            "memory_ids": sorted(set(memory_ids)),
            "stale_memory_ids": sorted(set(stale_memory_ids)),
            "retrieval_strategies": list(retrieval.strategies_used),
        }
        digest = compute_context_digest(packet_dict)
        packet_dict["digest"] = digest

        event_id = self.event_store.append(
            actor="orchestrator",
            kind="context.compiled",
            project_id=request.project_id,
            task_id=request.task_id,
            payload={
                "context_id": context_id,
                "state_version": request.state_version,
                "digest": digest,
                "token_count": total_tokens,
                "hard_budget": request.token_budget,
                "context_policy": policy_id,
                "memory_validity_enforced": enforce_memory_validity,
                "memory_ids": packet_dict["memory_ids"],
                "stale_memory_ids": packet_dict["stale_memory_ids"],
                "retrieval_strategies": packet_dict["retrieval_strategies"],
                "files_declared": packet_dict["files_declared"],
                "code_files": [item["path"] for item in code_context],
            },
        )
        packet_dict["compiled_event"] = event_id
        return ContextPacket(**packet_dict)
