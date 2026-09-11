"""Central Single-Writer Orchestrator governing authoritative state, tasks, and agents."""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import AgentAdapter, AgentBudget, AgentRunResult
from context.compiler import ContextCompiler
from context.request import ContextRequest
from context.retrieval import MemoryRetriever
from context.staleness import StalenessDetector
from isolation.worktree import WorktreeError, WorktreeManager
from memory.lifecycle import MemoryLifecycle
from runtime.budgets import BudgetAccountant
from runtime.gate import IntegrationGate
from runtime.leases import LeaseManager
from runtime.recovery import RecoveryEngine
from runtime.scheduler import TaskScheduler
from state.events import EventStore
from state.models import GateResult, GateStatus, PatchSubmission
from state.projection import DeterministicStateProjection


class Orchestrator:
    """Single authoritative writer for task execution and integration."""

    def __init__(
        self,
        event_store: EventStore,
        memory_lifecycle: MemoryLifecycle,
        repo_path: str | Path,
        project_id: str,
        verification_level: str = "V0",
        hard_task_usd: float = 5.0,
        hard_project_usd: float = 500.0,
        visible_test_cmd: Optional[List[str]] = None,
    ) -> None:
        self.event_store = event_store
        self.memory_lifecycle = memory_lifecycle
        self.repo_path = Path(repo_path).resolve()
        self.project_id = project_id
        self.hard_task_usd = hard_task_usd
        self.visible_test_cmd = visible_test_cmd

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
        return self.event_store.append(
            actor="orchestrator",
            kind="project.created",
            project_id=self.project_id,
            payload={"spec": spec, "constraints": constraints or []},
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
        """Run one task from versioned context through transactional integration."""
        task = self.scheduler.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not self.budgets.can_spend(task_id, 0.05):
            raise RuntimeError(f"Budget ceiling exceeded for task {task_id}")

        self.scheduler.dispatch_task(task_id, agent_id)
        dispatch_v = self.event_store.current_version(self.project_id)

        lease = None
        worktree_path: Optional[Path] = None
        try:
            if task.files_declared:
                lease = self.leases.request_lease(
                    resource=task.files_declared[0],
                    holder=agent_id,
                    task_id=task_id,
                )

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
            projection = self.get_projection()
            leases_info = (
                [{"resource": lease.resource, "fencing_token": lease.fencing_token}]
                if lease
                else []
            )
            packet = self.compiler.compile(
                request=context_req,
                retrieval=retrieval_res,
                project_state=projection.project.state,
                task_state=task,
                active_leases=leases_info,
            )

            worktree_path = self.worktree_mgr.create_worktree(task_id)
            agent_budget = AgentBudget(
                max_usd=self.hard_task_usd,
                max_tokens=task.token_budget,
            )
            agent_result: AgentRunResult = await agent.run(
                context=packet,
                workspace=worktree_path,
                budget=agent_budget,
            )

            self.budgets.record_consumption(
                usd=agent_result.cost_usd,
                tokens=(
                    agent_result.token_usage.get("prompt_tokens", 0)
                    + agent_result.token_usage.get("completion_tokens", 0)
                ),
                task_id=task_id,
            )

            if agent_result.status != "completed":
                self.event_store.append(
                    actor=agent_id,
                    kind="task.failed",
                    project_id=self.project_id,
                    task_id=task_id,
                    payload={"reason": f"agent_status={agent_result.status}"},
                )
                raise RuntimeError(
                    f"agent {agent_id} did not complete task {task_id}: {agent_result.status}"
                )

            # The candidate commit, not an arbitrary text field, is the unit of integration.
            candidate_sha = self.worktree_mgr.commit_candidate(
                task_id,
                message=f"arc({task_id}): candidate from {agent_id}",
            )
            diff = self.worktree_mgr.get_commit_diff(candidate_sha)

            patch_id = f"patch_{uuid.uuid4().hex[:8]}"
            submission = PatchSubmission(
                patch_id=patch_id,
                task_id=task_id,
                agent_id=agent_id,
                context_id=packet.context_id,
                dispatch_state_version=dispatch_v,
                candidate_commit_sha=candidate_sha,
                candidate_branch=self.worktree_mgr.branch_name(task_id),
                fencing_tokens=[lease.fencing_token] if lease else [],
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
                    "candidate_commit_sha": candidate_sha,
                    "candidate_branch": submission.candidate_branch,
                    "summary": agent_result.summary,
                    "memories_used": agent_result.memory_references,
                    "decisions": agent_result.decisions,
                    "assumptions": agent_result.assumptions,
                },
            )

            staleness = self.staleness_detector.evaluate_submission(
                submission=submission,
                project_id=self.project_id,
                dependency_task_ids=set(task.dependencies),
                declared_files=set(task.files_declared),
            )

            gate_result = self.gate.evaluate_submission(
                submission=submission,
                staleness_score=staleness.staleness_score,
                visible_test_cmd=self.visible_test_cmd,
            )

            if gate_result.status == GateStatus.ACCEPTED:
                # Memory is a derived projection over authoritative events. Process the
                # committed trajectory only after the candidate entered integration.
                latest_events = self.event_store.read_after(
                    dispatch_v,
                    project_id=self.project_id,
                )
                for event in latest_events:
                    self.memory_lifecycle.process_event(event)
            else:
                self.recovery.handle_failure(
                    task_id=task_id,
                    failure_type=gate_result.rejection_stage or "unknown_rejection",
                    details={"error": gate_result.error_detail},
                    attempt_count=task.attempt_count,
                )

            return gate_result
        except WorktreeError as exc:
            self.event_store.append(
                actor="orchestrator",
                kind="task.failed",
                project_id=self.project_id,
                task_id=task_id,
                payload={"reason": "worktree_error", "error": str(exc)},
            )
            raise
        finally:
            if lease:
                self.leases.release_lease(lease.resource, agent_id, task_id)
            if worktree_path is not None:
                self.worktree_mgr.remove_worktree(task_id)
