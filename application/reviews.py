"""Closed-loop pull-request supervision for persistent ARC workers.

GitHub is treated as an external review surface, not authoritative ARC state.
Normalized snapshots, feedback, and feedback-application decisions are emitted
into ARC's append-only event stream so the loop is replayable and inspectable.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from integrations.github_cli import GitHubCheck, GitHubCliClient, GitHubPullRequestSnapshot

if TYPE_CHECKING:  # pragma: no cover
    from application.app import ArcApplication


class ReviewStatus(BaseModel):
    session_id: str
    linked: bool = False
    pr_number: int | None = None
    pr_url: str = ""
    head_ref: str = ""
    base_ref: str = ""
    state: str = ""
    review_decision: str = ""
    merge_state_status: str = ""
    checks: list[GitHubCheck] = Field(default_factory=list)
    last_digest: str = ""
    pending_feedback: str = ""
    feedback_digest: str = ""
    applied_feedback_digest: str = ""
    updated_event: int = 0

    @property
    def failed_checks(self) -> list[GitHubCheck]:
        return [item for item in self.checks if item.failed]

    @property
    def pending_checks(self) -> list[GitHubCheck]:
        return [item for item in self.checks if item.pending]

    @property
    def healthy(self) -> bool:
        return (
            self.linked
            and self.state.upper() == "OPEN"
            and not self.failed_checks
            and not self.pending_checks
            and self.review_decision.upper() != "CHANGES_REQUESTED"
            and not self.pending_feedback
        )


class ReviewSyncResult(BaseModel):
    session_id: str
    status: ReviewStatus
    changed: bool
    feedback_applied: bool = False
    error: str = ""


class ReviewLoopManager:
    """Project external GitHub review state into ARC and route it to workers."""

    def __init__(self, app: "ArcApplication") -> None:
        self.app = app

    def _review_events(self, session_id: str | None = None) -> list[Any]:
        events = [
            event
            for event in self.app.event_store.read_all(project_id=self.app.project_id)
            if event.kind.startswith("session.pr_") or event.kind.startswith("session.review_")
        ]
        if session_id is None:
            return events
        return [
            event
            for event in events
            if (event.payload.get("session_id") or event.correlation_id) == session_id
        ]

    def status(self, session_id: str) -> ReviewStatus:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        status = ReviewStatus(session_id=session_id)
        for event in self._review_events(session_id):
            status.updated_event = event.id
            payload = event.payload
            if event.kind in {"session.pr_published", "session.pr_updated"}:
                status.linked = True
                status.pr_number = int(payload["pr_number"])
                status.pr_url = str(payload.get("pr_url") or "")
                status.head_ref = str(payload.get("head_ref") or session.branch)
                status.base_ref = str(payload.get("base_ref") or "main")
            elif event.kind == "session.review_synced":
                status.linked = True
                status.pr_number = int(payload.get("pr_number") or status.pr_number or 0) or None
                status.pr_url = str(payload.get("pr_url") or status.pr_url)
                status.state = str(payload.get("state") or "")
                status.review_decision = str(payload.get("review_decision") or "")
                status.merge_state_status = str(payload.get("merge_state_status") or "")
                status.last_digest = str(payload.get("digest") or "")
                status.checks = [GitHubCheck.model_validate(item) for item in payload.get("checks", [])]
                candidate_feedback = str(payload.get("actionable_feedback") or "")
                candidate_digest = str(payload.get("feedback_digest") or "")
                status.feedback_digest = candidate_digest
                status.pending_feedback = (
                    candidate_feedback
                    if candidate_digest and candidate_digest != status.applied_feedback_digest
                    else ""
                )
            elif event.kind == "session.review_feedback_applied":
                status.applied_feedback_digest = str(payload.get("digest") or "")
                if status.feedback_digest == status.applied_feedback_digest:
                    status.pending_feedback = ""
            elif event.kind == "session.review_feedback_cleared":
                status.pending_feedback = ""
                status.feedback_digest = ""
        return status

    def list(self) -> list[ReviewStatus]:
        return [self.status(item.session_id) for item in self.app.sessions.list()]

    @staticmethod
    def _git(workspace: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "git command failed").strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
        return result

    def doctor(self) -> dict[str, Any]:
        return GitHubCliClient(self.app.repo_path).doctor()

    def publish(
        self,
        session_id: str,
        *,
        base: str = "main",
        remote: str = "origin",
        title: str | None = None,
    ) -> ReviewStatus:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        if session.status not in self.app.sessions.ACTIVE:
            raise ValueError(f"Session {session_id} is {session.status.value}; cannot publish")
        workspace = Path(session.worktree_path)
        if not workspace.exists():
            raise RuntimeError(f"Session worktree is missing: {workspace}")

        task = self.app.get_task(session.task_id)
        if not task:
            raise ValueError(f"Task {session.task_id} not found")
        existing = self.status(session_id)

        dirty = bool(self._git(workspace, ["status", "--porcelain"]).stdout.strip())
        if dirty:
            # commit_candidate commits staged draft changes onto the task branch.
            # On a multi-commit review branch it may return an unattached squash
            # SHA for the ARC gate. A PR event must instead record the actual
            # public branch HEAD that `git push` publishes.
            self.app.orchestrator.worktree_mgr.commit_candidate(
                session.task_id,
                message=f"arc({session.task_id}): publish worker review from {session.agent_name}",
            )
            commit_sha = self._git(workspace, ["rev-parse", "HEAD"]).stdout.strip()
        else:
            commit_sha = self._git(workspace, ["rev-parse", "HEAD"]).stdout.strip()
            if not existing.linked:
                parent_count = int(
                    self._git(
                        workspace,
                        ["rev-list", "--count", f"{base}..HEAD"],
                        check=False,
                    ).stdout.strip()
                    or "0"
                )
                if parent_count == 0:
                    raise ValueError("Worker has no repository changes to publish")

        client = GitHubCliClient(workspace)
        pr_title = title or f"[ARC {session.task_id}] {task.goal}"
        body = (
            "Automated review branch published by ARC.\n\n"
            f"- Task: `{session.task_id}`\n"
            f"- Worker session: `{session_id}`\n"
            f"- Agent: `{session.agent_name}` ({session.provider})\n"
            f"- Context: `{session.context_id}` @ state v{session.dispatch_state_version}\n\n"
            "ARC remains authoritative for task/session state. GitHub checks and review feedback "
            "are imported as external review signals."
        )
        if existing.linked and existing.pr_number:
            snapshot = client.update_pr(existing.pr_number, branch=session.branch, remote=remote)
            kind = "session.pr_updated"
        else:
            snapshot = client.create_pr(
                branch=session.branch,
                base=base,
                title=pr_title,
                body=body,
                remote=remote,
            )
            kind = "session.pr_published"

        self.app.event_store.append(
            actor="review-supervisor",
            kind=kind,
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "pr_number": snapshot.number,
                "pr_url": snapshot.url,
                "head_ref": snapshot.head_ref or session.branch,
                "base_ref": snapshot.base_ref or base,
                "commit_sha": commit_sha,
                "remote": remote,
            },
        )
        self._record_snapshot(session_id, snapshot, force=True)
        return self.status(session_id)

    def _record_snapshot(
        self,
        session_id: str,
        snapshot: GitHubPullRequestSnapshot,
        *,
        force: bool = False,
    ) -> bool:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        previous = self.status(session_id)
        if not force and previous.last_digest == snapshot.digest:
            return False
        actionable = snapshot.actionable_feedback()
        feedback_digest = (
            hashlib.sha256(actionable.encode("utf-8")).hexdigest() if actionable else ""
        )
        self.app.event_store.append(
            actor="review-supervisor",
            kind="session.review_synced",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={
                "session_id": session_id,
                "pr_number": snapshot.number,
                "pr_url": snapshot.url,
                "state": snapshot.state,
                "review_decision": snapshot.review_decision,
                "merge_state_status": snapshot.merge_state_status,
                "checks": [item.model_dump(mode="json") for item in snapshot.checks],
                "failed_checks": len(snapshot.failed_checks),
                "pending_checks": len(snapshot.pending_checks),
                "digest": snapshot.digest,
                "healthy": snapshot.healthy,
                "actionable_feedback": actionable,
                "feedback_digest": feedback_digest,
            },
        )
        is_new_feedback = bool(
            actionable and feedback_digest != previous.applied_feedback_digest
        )
        if is_new_feedback:
            self.app.event_store.append(
                actor="review-supervisor",
                kind="session.review_feedback",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "digest": feedback_digest,
                    "snapshot_digest": snapshot.digest,
                    "content": actionable,
                },
            )
            self.app.event_store.append(
                actor="review-supervisor",
                kind="session.message",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={
                    "session_id": session_id,
                    "role": "system",
                    "content": "GitHub review update:\n\n" + actionable,
                },
            )
        elif not actionable and previous.pending_feedback:
            self.app.event_store.append(
                actor="review-supervisor",
                kind="session.review_feedback_cleared",
                project_id=self.app.project_id,
                task_id=session.task_id,
                correlation_id=session_id,
                payload={"session_id": session_id, "digest": snapshot.digest},
            )
        return True

    async def sync(self, session_id: str, *, auto_apply: bool = False) -> ReviewSyncResult:
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        current = self.status(session_id)
        if not current.linked or not current.pr_number:
            raise ValueError(f"Session {session_id} is not linked to a GitHub pull request")
        snapshot = GitHubCliClient(Path(session.worktree_path)).snapshot(current.pr_number)
        changed = self._record_snapshot(session_id, snapshot)
        applied = False
        refreshed = self.status(session_id)
        if auto_apply and refreshed.pending_feedback:
            applied = await self.apply_latest(session_id)
            refreshed = self.status(session_id)
        return ReviewSyncResult(
            session_id=session_id,
            status=refreshed,
            changed=changed,
            feedback_applied=applied,
        )

    async def apply_latest(self, session_id: str) -> bool:
        status = self.status(session_id)
        if not status.pending_feedback or not status.feedback_digest:
            return False
        if status.feedback_digest == status.applied_feedback_digest:
            return False
        session = self.app.sessions.get(session_id)
        if not session:
            raise ValueError(f"Worker session {session_id} not found")
        if session.status not in self.app.sessions.ACTIVE:
            raise ValueError(
                f"Session {session_id} is {session.status.value}; cannot apply review feedback"
            )
        prompt = (
            "Address the following GitHub review/CI feedback in the existing worker workspace. "
            "Inspect the actual failure before editing. Preserve the task goal and acceptance criteria. "
            "Do not weaken or delete valid tests merely to make checks pass.\n\n"
            + status.pending_feedback
        )
        await self.app.sessions.send(session_id, prompt)
        self.app.event_store.append(
            actor="review-supervisor",
            kind="session.review_feedback_applied",
            project_id=self.app.project_id,
            task_id=session.task_id,
            correlation_id=session_id,
            payload={"session_id": session_id, "digest": status.feedback_digest},
        )
        return True

    async def supervise_once(self, *, auto_apply: bool = False) -> list[ReviewSyncResult]:
        results: list[ReviewSyncResult] = []
        for session in self.app.sessions.list():
            current = self.status(session.session_id)
            if not current.linked or not current.pr_number:
                continue
            if session.status not in self.app.sessions.ACTIVE:
                continue
            try:
                results.append(await self.sync(session.session_id, auto_apply=auto_apply))
            except Exception as exc:
                self.app.event_store.append(
                    actor="review-supervisor",
                    kind="session.review_sync_failed",
                    project_id=self.app.project_id,
                    task_id=session.task_id,
                    correlation_id=session.session_id,
                    payload={"session_id": session.session_id, "error": str(exc)},
                )
                results.append(
                    ReviewSyncResult(
                        session_id=session.session_id,
                        status=current,
                        changed=False,
                        error=str(exc),
                    )
                )
        return results

    async def supervise(
        self,
        *,
        interval_seconds: float = 30.0,
        auto_apply: bool = False,
    ) -> None:
        if interval_seconds < 5.0:
            raise ValueError("Review supervision interval must be at least 5 seconds")
        while True:
            await self.supervise_once(auto_apply=auto_apply)
            await asyncio.sleep(interval_seconds)
