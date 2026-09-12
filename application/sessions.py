"""Persistent worker sessions for conversational coding-agent supervision.

A worker session binds one authoritative ARC task to one agent profile and one
isolated worktree. Session metadata and conversation are reconstructed from the
append-only event log; the worktree is the durable draft workspace. Provider
processes are intentionally *not* treated as durable state: ARC may re-launch a
provider on the same session/worktree after a restart.
"""

from __future__ import annotations

import asyncio
import subprocess
import uuid
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, Field

from adapters.base import AgentBudget, AgentRunResult, sanitize_failure_diagnostics
from adapters.cli_process import SubprocessCodingAgent, render_context_prompt
from context.compiler import ContextPacket
from context.request import ContextRequest
from state.models import GateResult, GateStatus, PatchSubmission, TaskStatus

if TYPE_CHECKING:  # pragma: no cover
    from application.app import ArcApplication


class SessionStatus(str, Enum):
    OPEN = "open"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STOPPED = "stopped"
    FAILED = "failed"


class SessionMessage(BaseModel):
    event_id: int
    ts: str
    role: Literal["user", "assistant", "system"]
    content: str


class WorkerSession(BaseModel):
    session_id: str
    task_id: str
    agent_name: str
    provider: str
    model: Optional[str] = None
    worktree_path: str
    branch: str
    context_id: str
    dispatch_state_version: int
    status: SessionStatus = SessionStatus.OPEN
    created_event: int
    updated_event: int
    messages: list[SessionMessage] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    last_summary: str = ""
    terminal_state: str = "offline"


class WorkerSessionManager:
    """Event-sourced session lifecycle layered above the task DAG."""

    ACTIVE = {
        SessionStatus.OPEN,
        SessionStatus.RUNNING,
        SessionStatus.NEEDS_INPUT,
        SessionStatus.FAILED,
    }

    def __init__(self, app: "ArcApplication") -> None:
        self.app = app

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------
    def _session_events(self) -> list[Any]:
        return [
            event
            for event in self.app.event_store.read_all(project_id=self.app.project_id)
            if event.kind.startswith("session.")
        ]

    def _project(self) -> dict[str, WorkerSession]:
        sessions: dict[str, WorkerSession] = {}
        for event in self._session_events():
            session_id = event.payload.get("session_id") or event.correlation_id
            if not session_id:
                continue
            if event.kind == "session.created":
                payload = event.payload
                sessions[session_id] = WorkerSession(
                    session_id=session_id,
                    task_id=payload["task_id"],
                    agent_name=payload["agent_name"],
                    provider=payload["provider"],
                    model=payload.get("model"),
                    worktree_path=payload["worktree_path"],
                    branch=payload["branch"],
                    context_id=payload["context_id"],
                    dispatch_state_version=int(payload["dispatch_state_version"]),
                    created_event=event.id,
                    updated_event=event.id,
                    status=SessionStatus.OPEN,
                )
                continue
            session = sessions.get(session_id)
            if not session:
                continue
            session.updated_event = event.id
            if event.kind == "session.message":
                role = event.payload.get("role", "system")
                if role not in {"user", "assistant", "system"}:
                    role = "system"
                session.messages.append(
                    SessionMessage(
                        event_id=event.id,
                        ts=event.ts,
                        role=role,
                        content=str(event.payload.get("content", "")),
                    )
                )
                if role == "assistant":
                    session.last_summary = str(event.payload.get("content", ""))
            elif event.kind == "session.turn_started":
                session.status = SessionStatus.RUNNING
            elif event.kind in {
                "session.turn_finished",
                "session.turn_cancelled",
                "session.resumed",
            }:
                session.status = SessionStatus.OPEN
                session.changed_files = list(event.payload.get("changed_files", session.changed_files))
            elif event.kind == "session.needs_input":
                session.status = SessionStatus.NEEDS_INPUT
            elif event.kind == "session.submitted":
                session.status = SessionStatus.SUBMITTED
            elif event.kind == "session.accepted":
                session.status = SessionStatus.ACCEPTED
            elif event.kind == "session.rejected":
                session.status = SessionStatus.REJECTED
            elif event.kind == "session.stopped":
                session.status = SessionStatus.STOPPED
            elif event.kind == "session.failed":
                session.status = SessionStatus.FAILED
            elif event.kind == "session.terminal_started":
                session.terminal_state = "live"
            elif event.kind in {"session.terminal_stopped", "session.terminal_lost"}:
                session.terminal_state = "offline"
        return sessions

    def list(self) -> list[WorkerSession]:
        return sorted(self._project().values(), key=lambda item: item.created_event, reverse=True)

    def get(self, session_id: str) -> WorkerSession | None:
        return self._project().get(session_id)

    def for_task(self, task_id: str) -> WorkerSession | None:
        candidates = [session for session in self.list() if session.task_id == task_id]
        return candidates[0] if candidates else None

    def _require(self, session_id: str) -> WorkerSession:
        session = self.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        return session

    def _created_event(self, session_id: str) -> Any:
        for event in self._session_events():
            if event.kind == "session.created" and (
                event.payload.get("session_id") == session_id or event.correlation_id == session_id
            ):
                return event
        raise ValueError(f"Worker session {session_id} has no creation event")

    def context_packet(self, session_id: str) -> ContextPacket:
        event = self._created_event(session_id)
        return ContextPacket.model_validate(event.payload["context_packet"])

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def create(self, task_id: str, *, agent_name: str | None = None) -> WorkerSession:
        self.app.require_initialized()
        task = self.app.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        if task.status != TaskStatus.READY:
            raise ValueError(f"Task {task_id} is {task.status.value}; worker sessions require READY tasks")
        existing = self.for_task(task_id)
        if existing and existing.status in self.ACTIVE:
            return existing

        name = agent_name
        if not name:
            try:
                name = self.app.route_task(task_id).agent_name
            except Exception:
                name = self.app.config.default_agent
        profile = self.app.config.agents.get(name)
        if not profile:
            raise ValueError(f"Agent profile {name!r} not found")

        session_id = f"S_{uuid.uuid4().hex[:8]}"
        worktree_path: Path | None = None
        try:
            # A session owns task execution until submit/stop. The task therefore
            # leaves the READY frontier immediately, preventing fleet execution
            # from racing the interactive worker.
            self.app.orchestrator.scheduler.dispatch_task(task_id, name)
            dispatch_v = self.app.event_store.current_version(self.app.project_id)
            task = self.app.get_task(task_id)
            assert task is not None

            request = ContextRequest(
                context_request_id=f"CR_{task_id}_{dispatch_v}",
                project_id=self.app.project_id,
                task_id=task_id,
                agent_id=name,
                state_version=dispatch_v,
                goal=task.goal,
                risk=task.risk,
                files_declared=task.files_declared,
                symbols=task.symbols,
                dependencies=task.dependencies,
                token_budget=task.token_budget,
            )
            retrieval = self.app.orchestrator.retriever.retrieve(request)
            projection = self.app.projection()
            packet = self.app.orchestrator.compiler.compile(
                request=request,
                retrieval=retrieval,
                project_state=projection.project.state,
                task_state=task,
                active_leases=[],
            )
            worktree_path = self.app.orchestrator.worktree_mgr.create_worktree(task_id)
            event_id = self.app.event_store.append(
                actor="orchestrator",
                kind="session.created",
                project_id=self.app.project_id,
                task_id=task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "task_id": task_id,
                    "agent_name": name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "worktree_path": str(worktree_path),
                    "branch": self.app.orchestrator.worktree_mgr.branch_name(task_id),
                    "context_id": packet.context_id,
                    "dispatch_state_version": dispatch_v,
                    "context_packet": packet.model_dump(mode="json"),
                },
            )
            self.app.event_store.append(
                actor="orchestrator",
                kind="session.message",
                project_id=self.app.project_id,
                task_id=task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "role": "system",
                    "content": (
                        f"Worker {session_id} opened for {task_id} with {name}. "
                        "Draft changes remain isolated until explicit submit."
                    ),
                    "created_event": event_id,
                },
            )
            return self._require(session_id)
        except Exception:
            if worktree_path is not None:
                self.app.orchestrator.worktree_mgr.remove_worktree(task_id)
            self.app.event_store.append(
                actor="orchestrator",
                kind="recovery.retry",
                project_id=self.app.project_id,
                task_id=task_id,
                payload={"reason": "worker session setup failed"},
            )
            raise

    def resume(self, session_id: str) -> WorkerSession:
        session = self._require(session_id)
        if session.status not in self.ACTIVE:
            raise ValueError(f"Session {session_id} is {session.status.value} and cannot resume")
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            raise RuntimeError(
                f"Session worktree is missing: {workspace}. ARC will not fabricate a recovered draft."
            )
        changed = self.changed_files(session_id)
        self.app.event_store.append(
            actor="operator",
            kind="session.resumed",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={"session_id": session_id, "changed_files": changed},
        )
        return self._require(session_id)

    async def send(
        self,
        session_id: str,
        instruction: str,
        *,
        turn_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> WorkerSession:
        session = self._require(session_id)
        if session.status not in self.ACTIVE:
            raise ValueError(f"Session {session_id} is {session.status.value}; it is not interactive")
        if not instruction.strip():
            raise ValueError("Instruction cannot be empty")
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            raise RuntimeError(f"Session worktree is missing: {workspace}")

        turn_id = turn_id or f"TURN_{uuid.uuid4().hex[:10]}"
        sequence = 0

        async def record_output(stream: str, content: str) -> None:
            nonlocal sequence
            if not content:
                return
            sequence += 1
            self.app.event_store.append(
                actor=session.agent_name,
                kind="session.turn_output",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "sequence": sequence,
                    "stream": stream,
                    "content": content,
                },
            )

        self.app.event_store.append(
            actor="operator",
            kind="session.message",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "turn_id": turn_id,
                "role": "user",
                "content": instruction.strip(),
            },
        )
        self.app.event_store.append(
            actor=session.agent_name,
            kind="session.turn_started",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={"session_id": session_id, "turn_id": turn_id},
        )

        packet = self.context_packet(session_id)
        profile = self.app.config.agents.get(session.agent_name)
        if not profile:
            raise ValueError(f"Agent profile {session.agent_name!r} no longer exists")
        adapter = self.app.build_agent(profile)
        budget = AgentBudget(
            max_usd=self.app.config.hard_task_usd,
            max_tokens=packet.budget_remaining_tokens or 24000,
        )

        try:
            if profile.provider == "mock":
                if cancel_event is not None and cancel_event.is_set():
                    result = AgentRunResult(
                        status="cancelled",
                        summary="Mock worker turn cancelled before execution",
                        memory_references=list(packet.memory_ids),
                    )
                else:
                    await record_output("stdout", f"mock: applying {instruction.strip()}\n")
                    target = workspace / ".arc-mock" / f"{session.session_id}.txt"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("a", encoding="utf-8") as handle:
                        handle.write(f"\n# instruction: {instruction.strip()}\n")
                    result = AgentRunResult(
                        status="completed",
                        patch_ref="WORKTREE",
                        summary=f"Mock worker applied instruction: {instruction.strip()}",
                        memory_references=list(packet.memory_ids),
                        token_usage={"prompt_tokens": 0, "completion_tokens": 0},
                        cost_usd=0.0,
                    )
            elif isinstance(adapter, SubprocessCodingAgent):
                transcript = self._require(session_id).messages[-12:]
                prompt = self._render_turn_prompt(packet, transcript, instruction)
                result = await adapter.run_prompt(
                    prompt=prompt,
                    workspace=workspace,
                    budget=budget,
                    memory_references=list(packet.memory_ids),
                    output_callback=record_output,
                    cancel_event=cancel_event,
                )
            else:
                result = await adapter.run(context=packet, workspace=workspace, budget=budget)

            self.app.orchestrator.budgets.record_consumption(
                usd=result.cost_usd,
                tokens=(
                    result.token_usage.get("prompt_tokens", 0)
                    + result.token_usage.get("completion_tokens", 0)
                ),
                task_id=session.task_id,
            )

            self.app.orchestrator._persist_provider_telemetry(  # noqa: SLF001 - shared runtime boundary
                task_id=session.task_id,
                agent_id=session.agent_name,
                result=result,
            )

            changed = self.changed_files(session_id)
            if result.status == "cancelled":
                self.app.event_store.append(
                    actor="operator",
                    kind="session.turn_cancelled",
                    project_id=self.app.project_id,
                    task_id=session.task_id,
                    correlation_id=session_id,
                    payload={
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "changed_files": changed,
                        "summary": result.summary,
                    },
                )
                self.app.event_store.append(
                    actor="orchestrator",
                    kind="session.message",
                    project_id=self.app.project_id,
                    task_id=session.task_id,
                    correlation_id=session_id,
                    payload={
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "role": "system",
                        "content": result.summary or "Provider turn cancelled by operator.",
                    },
                )
                return self._require(session_id)

            if result.status != "completed":
                diagnostics = sanitize_failure_diagnostics(result)
                self.app.event_store.append(
                    actor=session.agent_name,
                    kind="provider.failed",
                    project_id=self.app.project_id,
                    task_id=session.task_id,
                    correlation_id=session_id,
                    payload=diagnostics,
                )
                raise RuntimeError(f"agent turn ended with status={result.status}: {result.summary}")

            summary = result.summary or f"{session.agent_name} completed the instruction"
            self.app.event_store.append(
                actor=session.agent_name,
                kind="session.message",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "role": "assistant",
                    "content": summary,
                },
            )
            self.app.event_store.append(
                actor=session.agent_name,
                kind="session.turn_finished",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "changed_files": changed,
                    "tool_trace": result.tool_trace,
                },
            )
        except asyncio.CancelledError:
            changed = self.changed_files(session_id)
            self.app.event_store.append(
                actor="orchestrator",
                kind="session.turn_cancelled",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "changed_files": changed,
                    "summary": "Provider turn cancelled because its supervisor stopped.",
                },
            )
            raise
        except Exception as exc:
            diagnostics = {
                "reason": "session_turn_exception",
                "agent_status": "failed",
                "agent_summary": str(exc),
                "failure_classification": "UNKNOWN_PROVIDER_FAILURE",
            }
            self.app.event_store.append(
                actor=session.agent_name,
                kind="session.failed",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={"session_id": session_id, "turn_id": turn_id, "error": str(exc), **diagnostics},
            )
            raise
        return self._require(session_id)

    async def submit(self, session_id: str) -> GateResult:
        session = self._require(session_id)
        if session.status not in self.ACTIVE:
            raise ValueError(f"Session {session_id} is {session.status.value}; it cannot submit")
        task = self.app.get_task(session.task_id)
        if not task:
            raise ValueError(f"Task {session.task_id} not found")
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            raise RuntimeError(f"Session worktree is missing: {workspace}")

        leases = []
        try:
            leases = self.app.orchestrator._acquire_task_leases(  # noqa: SLF001 - shared runtime boundary
                session.task_id,
                session.agent_name,
                task.files_declared,
            )
            candidate_sha = self.app.orchestrator.worktree_mgr.commit_candidate(
                session.task_id,
                message=f"arc({session.task_id}): session candidate from {session.agent_name}",
            )
            diff = self.app.orchestrator.worktree_mgr.get_commit_diff(candidate_sha)
            patch_id = f"patch_{uuid.uuid4().hex[:8]}"
            packet = self.context_packet(session_id)
            submission = PatchSubmission(
                patch_id=patch_id,
                task_id=session.task_id,
                agent_id=session.agent_name,
                context_id=session.context_id,
                dispatch_state_version=session.dispatch_state_version,
                candidate_commit_sha=candidate_sha,
                candidate_branch=session.branch,
                fencing_tokens=[lease.fencing_token for lease in leases],
                diff=diff,
                summary=session.last_summary or f"Worker session {session_id}",
                memories_used=list(packet.memory_ids),
                decisions=[],
                assumptions=[],
            )
            self.app.event_store.append(
                actor=session.agent_name,
                kind="task.submitted",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "patch_id": patch_id,
                    "context_id": session.context_id,
                    "dispatch_state_version": session.dispatch_state_version,
                    "candidate_commit_sha": candidate_sha,
                    "candidate_branch": session.branch,
                    "summary": submission.summary,
                    "memories_used": submission.memories_used,
                    "session_id": session_id,
                },
            )
            self.app.event_store.append(
                actor="orchestrator",
                kind="session.submitted",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={"session_id": session_id, "candidate_commit_sha": candidate_sha},
            )

            async with self.app.orchestrator._integration_lock:  # noqa: SLF001
                staleness = self.app.orchestrator.staleness_detector.evaluate_submission(
                    submission=submission,
                    project_id=self.app.project_id,
                    dependency_task_ids=set(task.dependencies),
                    declared_files=set(task.files_declared),
                )
                result = self.app.orchestrator.gate.evaluate_submission(
                    submission=submission,
                    staleness_score=staleness.staleness_score,
                    visible_test_cmd=self.app.config.visible_test_cmd or None,
                )
                if result.status == GateStatus.ACCEPTED:
                    for event in self.app.event_store.read_after(
                        session.dispatch_state_version,
                        project_id=self.app.project_id,
                    ):
                        if event.task_id == session.task_id:
                            self.app.memory.process_event(event)
                    kind = "session.accepted"
                else:
                    self.app.orchestrator.recovery.handle_failure(
                        task_id=session.task_id,
                        failure_type=result.rejection_stage or "session_gate_rejection",
                        details={"error": result.error_detail, "session_id": session_id},
                        attempt_count=task.attempt_count,
                    )
                    kind = "session.rejected"

            self.app.event_store.append(
                actor="orchestrator",
                kind=kind,
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "gate_run_id": result.gate_run_id,
                    "status": result.status.value,
                    "merged_commit_sha": result.merged_commit_sha,
                    "error": result.error_detail,
                },
            )
            return result
        finally:
            for lease in reversed(leases):
                self.app.orchestrator.leases.release_lease(
                    lease.resource, session.agent_name, session.task_id
                )
            # Accepted/rejected submissions are immutable. Keep the transcript in
            # events but remove the draft workspace to avoid stale editing.
            refreshed = self.get(session_id)
            if refreshed and refreshed.status in {SessionStatus.ACCEPTED, SessionStatus.REJECTED}:
                self.app.orchestrator.worktree_mgr.remove_worktree(session.task_id)

    def stop(self, session_id: str, *, reason: str = "operator stopped worker") -> WorkerSession:
        session = self._require(session_id)
        if session.status not in self.ACTIVE:
            return session
        self.app.event_store.append(
            actor="operator",
            kind="session.stopped",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={"session_id": session_id, "reason": reason},
        )
        task = self.app.get_task(session.task_id)
        if task and task.status in {TaskStatus.DISPATCHED, TaskStatus.SUBMITTED}:
            self.app.event_store.append(
                actor="orchestrator",
                kind="recovery.retry",
                project_id=self.app.project_id,
                task_id=session.task_id,
                payload={"reason": f"session {session_id} stopped: {reason}"},
            )
        self.app.orchestrator.worktree_mgr.remove_worktree(session.task_id)
        return self._require(session_id)

    # ------------------------------------------------------------------
    # Workspace inspection + native terminal handoff
    # ------------------------------------------------------------------
    def changed_files(self, session_id: str) -> list[str]:
        session = self._require(session_id)
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            return list(session.changed_files)
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        files = []
        for line in result.stdout.splitlines():
            if len(line) >= 4:
                files.append(line[3:].strip())
        return sorted(set(files))

    def diff(self, session_id: str, *, max_chars: int = 120000) -> str:
        session = self._require(session_id)
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            return ""
        tracked = subprocess.run(
            ["git", "diff", "--no-ext-diff", "HEAD"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        pieces = [tracked]
        status = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
        for raw in status[:20]:
            path = workspace / raw
            if not path.is_file():
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            pieces.append(f"\n--- /dev/null\n+++ b/{raw}\n@@ new file @@\n{body[:12000]}")
        return "".join(pieces)[:max_chars]

    def native_command(self, session_id: str) -> list[str]:
        session = self._require(session_id)
        profile = self.app.config.agents.get(session.agent_name)
        if not profile:
            raise ValueError(f"Agent profile {session.agent_name!r} not found")
        if profile.command_override:
            import shlex

            return shlex.split(profile.command_override)
        command: list[str]
        if profile.provider == "codex":
            command = ["codex"]
            if profile.model:
                command += ["--model", profile.model]
        elif profile.provider == "claude":
            command = ["claude"]
            if profile.model:
                command += ["--model", profile.model]
        elif profile.provider == "antigravity":
            command = ["agy"]
        elif profile.provider == "opencode":
            command = ["opencode"]
        else:
            raise ValueError(f"Provider {profile.provider!r} has no native terminal interface")
        return command

    def mark_terminal(self, session_id: str, *, live: bool) -> None:
        session = self._require(session_id)
        self.app.event_store.append(
            actor="operator",
            kind="session.terminal_started" if live else "session.terminal_stopped",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={"session_id": session_id},
        )

    @staticmethod
    def _render_turn_prompt(
        packet: ContextPacket,
        transcript: list[SessionMessage],
        instruction: str,
    ) -> str:
        history = "\n".join(
            f"{message.role.upper()}: {message.content[-4000:]}" for message in transcript
        )
        return (
            render_context_prompt(packet)
            + "\n\nARC_PERSISTENT_WORKER_SESSION:\n"
            + "You are continuing an existing isolated worker session. Preserve useful draft changes "
            + "already present in the worktree. Do not commit; ARC submits through its integration gate.\n"
            + (f"\nRECENT_SESSION_TRANSCRIPT:\n{history}\n" if history else "")
            + f"\nLATEST_OPERATOR_INSTRUCTION:\n{instruction.strip()}\n"
        )
