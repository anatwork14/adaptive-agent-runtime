"""State-version staleness detection for agent submissions."""

from dataclasses import dataclass
from typing import List, Set

from memory.lifecycle import MemoryLifecycle
from memory.models import MemoryStatus
from state.events import EventStore
from state.models import PatchSubmission


@dataclass
class StalenessAssessment:
    staleness_score: float
    is_stale: bool
    requires_revalidation: bool
    delta_events_count: int
    relevant_delta_events: int
    invalidated_memory_count: int
    superseded_memory_count: int
    dependency_change_count: int
    details: List[str]


class StalenessDetector:
    """Detect whether an agent's ContextPacket became stale during isolated execution."""

    def __init__(
        self,
        event_store: EventStore,
        memory_lifecycle: MemoryLifecycle,
        revalidate_threshold: float = 0.3,
        reject_threshold: float = 0.8,
    ) -> None:
        self.event_store = event_store
        self.memory_lifecycle = memory_lifecycle
        self.revalidate_threshold = revalidate_threshold
        self.reject_threshold = reject_threshold

    @staticmethod
    def _is_own_execution_event(kind: str) -> bool:
        """Return true for events that describe this attempt rather than mutate its inputs.

        v0.6 persistent workers can emit many conversation/terminal supervision
        events between dispatch and submit. Those events are important for replay,
        but they do not make the worker's own immutable ContextPacket stale. Real
        dependency changes, project-spec changes, memory invalidation, and
        declared-file changes remain relevant below.
        """
        if kind.startswith("session.") or kind.startswith("shell."):
            return True
        return kind in {
            "context.compiled",
            "task.dispatched",
            "task.submitted",
            "budget.consumed",
            "budget.reserved",
            "lease.granted",
            "lease.released",
        }

    def evaluate_submission(
        self,
        submission: PatchSubmission,
        project_id: str,
        dependency_task_ids: Set[str],
        declared_files: Set[str],
    ) -> StalenessAssessment:
        """Compute staleness score based on semantic delta events since dispatch."""
        dispatch_v = submission.dispatch_state_version
        delta_events = self.event_store.read_after(dispatch_v, project_id=project_id)

        details: List[str] = []
        relevant_events = 0
        dep_changes = 0

        for ev in delta_events:
            # Skip the current task's own execution/supervision trail. In
            # particular, a persistent worker may accumulate arbitrarily many
            # session.message/session.turn_* events before submit; counting those
            # as external drift would make long conversations self-invalidating.
            if ev.task_id == submission.task_id and self._is_own_execution_event(ev.kind):
                continue

            # Check if another actor changed the task or one of its dependencies.
            if ev.task_id == submission.task_id and ev.actor != submission.agent_id:
                relevant_events += 1
                details.append(f"Event {ev.id} touched task {submission.task_id}: {ev.kind}")
            elif ev.task_id in dependency_task_ids:
                relevant_events += 1
                dep_changes += 1
                details.append(f"Event {ev.id} changed dependency {ev.task_id}: {ev.kind}")

            # Check if an event explicitly reports mutation of a declared file.
            touched_files = ev.payload.get("files", [])
            if any(path in declared_files for path in touched_files):
                relevant_events += 1
                details.append(f"Event {ev.id} touched declared files: {touched_files}")

            # Project constraints/spec are always semantic inputs.
            if ev.kind in ("project.constraint_added", "project.constraint_removed", "project.spec_updated"):
                relevant_events += 1
                details.append(f"Event {ev.id} updated project constraints/spec: {ev.kind}")

        # Check whether memories referenced by the immutable packet have since
        # been superseded or invalidated.
        invalidated_memories = 0
        superseded_memories = 0
        for mem_id in submission.memories_used:
            mem = self.memory_lifecycle.get_memory(mem_id)
            if mem:
                if mem.status == MemoryStatus.SUPERSEDED:
                    superseded_memories += 1
                    details.append(f"Used memory {mem_id} was superseded by {mem.superseded_by}")
                elif mem.status in (MemoryStatus.DELETED, MemoryStatus.DISPUTED):
                    invalidated_memories += 1
                    details.append(f"Used memory {mem_id} is currently {mem.status}")

        raw_score = (
            (relevant_events * 0.3)
            + (superseded_memories * 0.5)
            + (invalidated_memories * 0.4)
            + (dep_changes * 0.4)
        )
        normalized_score = min(1.0, raw_score)

        return StalenessAssessment(
            staleness_score=round(normalized_score, 4),
            is_stale=normalized_score >= self.reject_threshold,
            requires_revalidation=normalized_score >= self.revalidate_threshold,
            delta_events_count=len(delta_events),
            relevant_delta_events=relevant_events,
            invalidated_memory_count=invalidated_memories,
            superseded_memory_count=superseded_memories,
            dependency_change_count=dep_changes,
            details=details,
        )
