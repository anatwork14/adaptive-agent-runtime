"""Central Single-Writer Orchestrator governing authoritative state, tasks, and agents."""

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from adapters.base import (
    AgentAdapter,
    AgentBudget,
    AgentRunResult,
    sanitize_failure_diagnostics,
)
from adapters.cli_process import AgentAdapterUnavailable
from context.compiler import ContextCompiler
from context.policy import ContextPolicy, RuntimeContextPolicy
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
from state.models import GateResult, GateStatus, Lease, PatchSubmission
from state.projection import DeterministicStateProjection


class LeaseUnavailableError(RuntimeError):
    """Transient task deferral because another agent owns a declared surface."""


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
        visible_test_harness: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.event_store = event_store
        self.memory_lifecycle = memory_lifecycle
        self.memory_lifecycle.bind_event_store(event_store)
        self.repo_path = Path(repo_path).resolve()
        self.project_id = project_id
        self.hard_task_usd = hard_task_usd
        self.visible_test_cmd = visible_test_cmd
        self.visible_test_harness = dict(visible_test_harness or {})

        self.scheduler = TaskScheduler(event_store, project_id)
        self.budgets = BudgetAccountant(event_store, project_id, hard_task_usd, hard_project_usd)
        self.leases = LeaseManager(event_store, project_id)
        self.gate = IntegrationGate(
            event_store,
            project_id,
            self.repo_path,
            verification_level,
            visible_test_harness=self.visible_test_harness,
        )
        self.recovery = RecoveryEngine(event_store, project_id)
        self.worktree_mgr = WorktreeManager(self.repo_path)

        self.retriever = MemoryRetriever(self.memory_lifecycle)
        self.compiler = ContextCompiler(self.event_store, repo_path=self.repo_path)
        self.staleness_detector = StalenessDetector(self.event_store, self.memory_lifecycle)
        # Agent work may be concurrent. Verification/integration remains a
        # single-writer critical section by construction rather than by event-loop accident.
        self._integration_lock = asyncio.Lock()

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
        task_type: str = "code",
        required_capabilities: Optional[List[str]] = None,
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
                "task_type": task_type,
                "required_capabilities": required_capabilities or [],
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

    def _acquire_task_leases(
        self, task_id: str, agent_id: str, resources: List[str]
    ) -> List[Lease]:
        acquired: List[Lease] = []
        for resource in sorted(set(resources)):
            lease = self.leases.request_lease(resource=resource, holder=agent_id, task_id=task_id)
            if lease is None:
                for held in reversed(acquired):
                    self.leases.release_lease(held.resource, agent_id, task_id)
                raise LeaseUnavailableError(
                    f"Task {task_id} deferred: declared resource {resource!r} is already leased"
                )
            acquired.append(lease)
        return acquired

    def _persist_provider_telemetry(
        self,
        *,
        task_id: str,
        agent_id: str,
        result: AgentRunResult,
    ) -> None:
        """Persist observable provider boundaries without storing raw output."""
        if not result.provider_events and not result.provider_lifecycle:
            return

        for item in result.provider_events:
            event_name = item.get("event")
            if not isinstance(event_name, str) or not (
                event_name.startswith("provider.") or event_name == "cli.prompt_written"
            ):
                continue
            if event_name == "provider.failed":
                # The failure event below carries the complete sanitized
                # diagnostic payload, including the failed boundary.
                continue
            self.event_store.append(
                actor=agent_id,
                kind=event_name,
                project_id=self.project_id,
                task_id=task_id,
                payload={
                    "observed": True,
                    "provider_outcome": result.provider_outcome,
                    "provider_returncode": result.provider_returncode,
                },
            )

        self.event_store.append(
            actor=agent_id,
            kind="provider.lifecycle",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "provider_lifecycle": result.provider_lifecycle,
                "provider_outcome": result.provider_outcome,
                "provider_returncode": result.provider_returncode,
                "token_usage": result.token_usage,
                "provider_tokens": result.token_usage.get("prompt_tokens", 0)
                + result.token_usage.get("completion_tokens", 0),
                "token_usage_observed": bool(result.token_usage),
            },
        )

    async def execute_task(
        self,
        task_id: str,
        agent: AgentAdapter,
        agent_id: str,
        *,
        context_policy: ContextPolicy | None = None,
    ) -> GateResult:
        """Run one task from a selected context policy through one shared gate path.

        ``context_policy`` changes only context construction. Leases, provider
        budget, worktree isolation, candidate creation, staleness detection,
        transactional integration, recovery, and durable memory processing remain
        identical across research baselines. Production callers omit the argument
        and receive the normal B7 provenance-aware runtime policy.
        """
        task = self.scheduler.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if not self.budgets.can_spend(task_id, 0.05):
            raise RuntimeError(f"Budget ceiling exceeded for task {task_id}")

        leases: List[Lease] = []
        worktree_path: Optional[Path] = None
        try:
            leases = self._acquire_task_leases(task_id, agent_id, task.files_declared)
            self.scheduler.dispatch_task(task_id, agent_id)
            dispatch_v = self.event_store.current_version(self.project_id)

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
            projection = self.get_projection()
            leases_info = [
                {"resource": lease.resource, "fencing_token": lease.fencing_token}
                for lease in leases
            ]
            policy = context_policy or RuntimeContextPolicy(self.retriever, self.compiler)
            build = policy.build(
                request=context_req,
                project_state=projection.project.state,
                task_state=task,
                active_leases=leases_info,
            )
            packet = build.packet
            self.event_store.append(
                actor="orchestrator",
                kind="context.policy_measured",
                project_id=self.project_id,
                task_id=task_id,
                payload={
                    "context_id": packet.context_id,
                    "context_policy": build.policy_id,
                    "retrieval_latency_ms": build.retrieval_latency_ms,
                    "context_compile_latency_ms": build.compile_latency_ms,
                    "retrieval_strategies": list(build.retrieval_strategies),
                },
            )

            worktree_path = self.worktree_mgr.create_worktree(task_id)
            agent_budget = AgentBudget(
                max_usd=self.hard_task_usd,
                max_tokens=task.token_budget,
            )
            try:
                agent_result: AgentRunResult = await agent.run(
                    context=packet,
                    workspace=worktree_path,
                    budget=agent_budget,
                )
            except AgentAdapterUnavailable as exc:
                detail = str(exc)
                classification = (
                    "CLI_NOT_FOUND" if "not found" in detail.lower() else "CONFIGURATION_ERROR"
                )
                agent_result = AgentRunResult(
                    status="failed",
                    summary=detail,
                    failure_classification=classification,
                    provider_outcome="not_found"
                    if classification == "CLI_NOT_FOUND"
                    else "launch_error",
                    stderr_tail=detail[-4000:],
                )

            self._persist_provider_telemetry(
                task_id=task_id,
                agent_id=agent_id,
                result=agent_result,
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
                diagnostics = sanitize_failure_diagnostics(agent_result)
                self.event_store.append(
                    actor=agent_id,
                    kind="provider.failed",
                    project_id=self.project_id,
                    task_id=task_id,
                    payload=diagnostics,
                )
                self.event_store.append(
                    actor=agent_id,
                    kind="task.failed",
                    project_id=self.project_id,
                    task_id=task_id,
                    payload=diagnostics,
                )
                raise RuntimeError(
                    f"agent {agent_id} did not complete task {task_id}: {agent_result.status}"
                )

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
                fencing_tokens=[lease.fencing_token for lease in leases],
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

            async with self._integration_lock:
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
                    visible_test_harness=self.visible_test_harness,
                )

                if gate_result.status == GateStatus.ACCEPTED:
                    latest_events = self.event_store.read_after(
                        dispatch_v,
                        project_id=self.project_id,
                    )
                    for event in latest_events:
                        if event.task_id == task_id:
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
            for lease in reversed(leases):
                self.leases.release_lease(lease.resource, agent_id, task_id)
            if worktree_path is not None:
                self.worktree_mgr.remove_worktree(task_id)
