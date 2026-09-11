"""Central Single-Writer Orchestrator governing authoritative state, tasks, and agents."""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextCompiler, ContextPacket
from context.request import ContextRequest
from context.retrieval import MemoryRetriever
from context.staleness import StalenessDetector
from isolation.worktree import WorktreeManager
from memory.lifecycle import MemoryLifecycle
from runtime.budgets import BudgetAccountant
from runtime.gate import IntegrationGate
from runtime.leases import LeaseManager
from runtime.recovery import RecoveryEngine, RecoveryStrategy
from runtime.scheduler import TaskScheduler
from state.events import EventStore
from state.models import (
    GateResult,
    GateStatus,
    PatchSubmission,
    ProjectState,
    TaskState,
    TaskStatus,
)
from state.projection import DeterministicStateProjection


class Orchestrator:
    """The single authoritative writer orchestrating tasks, context compilation, agents, and gate integration."""

    def __init__(
        self,
        event_store: EventStore,
        memory_lifecycle: MemoryLifecycle,
        repo_path: str | Path,
        project_id: str,
        verification_level: str = "V0",
        hard_task_usd: float = 5.0,
        hard_project_usd: float = 500.0,
    ) -> None:
        self.event_store = event_store
        self.memory_lifecycle = memory_lifecycle
        self.repo_path = Path(repo_path).resolve()
        self.project_id = project_id

        self.scheduler = TaskScheduler(event_store, project_id)
        self.budgets = BudgetAccountant(event_store, project_id, hard_task_usd, hard_project_usd)
        self.leases = LeaseManager(event_store, project_id)
        self.gate = IntegrationGate(event_store, project_id, self.repo_path, verification_level)
        self.recovery = RecoveryEngine(event_store, project_id)
        self.worktree_mgr = WorktreeManager(self.repo_path)

        self.retriever = MemoryRetriever(self.memory_lifecycle)
        self.compiler = ContextCompiler(self.event_store)
        self.staleness_detector = StalenessDetector(self.event_store, self.memory_lifecycle)

    def init_project(self, spec: Dict[str, Any], constraints: Optional[List[str]] = None) -> int:
        """Initialize authoritative project state."""
        return self.event_store.append(
            actor="orchestrator",
            kind="project.created",
            project_id=self.project_id,
            payload={
                "spec": spec,
                "constraints": constraints or [],
            },
        )

    def create_task(
        self,
        task_id: str,
        goal: str,
        dependencies: Optional[List[str]] = None,
        files_declared: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        risk: float = 0.5,
        token_budget: int = 24000,
    ) -> int:
        """Create a new task in the authoritative DAG."""
        return self.event_store.append(
            actor="orchestrator",
            kind="task.created",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "task_id": task_id,
                "goal": goal,
                "dependencies": dependencies or [],
                "files_declared": files_declared or [],
                "symbols": symbols or [],
                "acceptance_criteria": acceptance_criteria or [],
                "risk": risk,
                "token_budget": token_budget,
            },
        )

    def get_projection(self) -> DeterministicStateProjection:
        events = self.event_store.read_all(project_id=self.project_id)
        return DeterministicStateProjection.replay_from_events(self.project_id, events)

    async def execute_task(
        self,
        task_id: str,
        agent: AgentAdapter,
        agent_id: str,
    ) -> GateResult:
        """End-to-end task execution workflow: context -> isolation -> agent -> patch -> gate -> event."""
        task = self.scheduler.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # 1. Dispatch task and check budget
        current_v = self.event_store.current_version(self.project_id)
        if not self.budgets.can_spend(task_id, 0.05):
            raise RuntimeError(f"Budget ceiling exceeded for task {task_id}")

        self.scheduler.dispatch_task(task_id, agent_id)
        dispatch_v = self.event_store.current_version(self.project_id)

        # 2. Grant lease for declared files
        lease = None
        if task.files_declared:
            lease = self.leases.request_lease(
                resource=task.files_declared[0],
                holder=agent_id,
                task_id=task_id,
            )

        # 3. Compile context packet (Section 34)
        context_req = ContextRequest(
            context_request_id=f"CR_{task_id}_{dispatch_v}",
            project_id=self.project_id,
            task_id=task_id,
            agent_id=agent_id,
            state_version=dispatch_v,
            goal=task.goal,
            risk=task.risk,
            files_declared=task.files_declared,
            symbols=task.symbols,
            dependencies=task.dependencies,
            token_budget=task.token_budget,
        )
        retrieval_res = self.retriever.retrieve(context_req)
        proj = self.get_projection()

        leases_info = [{"resource": lease.resource, "fencing_token": lease.fencing_token}] if lease else []
        packet = self.compiler.compile(
            request=context_req,
            retrieval=retrieval_res,
            project_state=proj.project.state,
            task_state=task,
            active_leases=leases_info,
        )

        # 4. Prepare isolated worktree
        worktree_path = self.worktree_mgr.create_worktree(task_id)

        # 5. Run agent in isolation
        agent_budget = AgentBudget(
            max_usd=5.0,
            max_tokens=task.token_budget,
        )
        agent_result: AgentRunResult = await agent.run(
            context=packet,
            workspace=worktree_path,
            budget=agent_budget,
        )

        # Account for consumed budget
        self.budgets.record_consumption(
            usd=agent_result.cost_usd,
            tokens=agent_result.token_usage.get("prompt_tokens", 0) + agent_result.token_usage.get("completion_tokens", 0),
            task_id=task_id,
        )

        # 6. Formulate patch submission (Invariant I9)
        patch_id = f"patch_{uuid.uuid4().hex[:8]}"
        diff = agent_result.diff or self.worktree_mgr.get_diff(task_id)
        fencing_tokens = [lease.fencing_token] if lease else []

        submission = PatchSubmission(
            patch_id=patch_id,
            task_id=task_id,
            agent_id=agent_id,
            context_id=packet.context_id,
            dispatch_state_version=dispatch_v,
            fencing_tokens=fencing_tokens,
            diff=diff,
            summary=agent_result.summary,
            memories_used=agent_result.memory_references,
            decisions=agent_result.decisions,
            assumptions=agent_result.assumptions,
        )

        self.event_store.append(
            actor=agent_id,
            kind="task.submitted",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "patch_id": patch_id,
                "context_id": packet.context_id,
                "dispatch_state_version": dispatch_v,
                "summary": agent_result.summary,
                "memories_used": agent_result.memory_references,
                "decisions": agent_result.decisions,
                "assumptions": agent_result.assumptions,
            },
        )

        # 7. Check staleness before integration gate (Section 23)
        staleness_assessment = self.staleness_detector.evaluate_submission(
            submission=submission,
            project_id=self.project_id,
            dependency_task_ids=set(task.dependencies),
            declared_files=set(task.files_declared),
        )

        # 8. Evaluate integration gate
        gate_res = self.gate.evaluate_submission(
            submission=submission,
            staleness_score=staleness_assessment.staleness_score,
        )

        # 9. Handle gate outcome
        if gate_res.status == GateStatus.ACCEPTED:
            # Memory lifecycle processes event (extracts decisions, procedures)
            latest_events = self.event_store.read_after(dispatch_v, project_id=self.project_id)
            for ev in latest_events:
                self.memory_lifecycle.process_event(ev)
        else:
            # Recovery workflow
            strat = self.recovery.handle_failure(
                task_id=task_id,
                failure_type=gate_res.rejection_stage or "unknown_rejection",
                details={"error": gate_res.error_detail},
                attempt_count=task.attempt_count,
            )

        # Cleanup lease and worktree
        if lease:
            self.leases.release_lease(lease.resource, agent_id, task_id)
        self.worktree_mgr.remove_worktree(task_id)

        return gate_res
