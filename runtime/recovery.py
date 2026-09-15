"""Recovery engine for task and context-level failures."""

from enum import Enum
from typing import Any, Dict

from state.events import EventStore


class RecoveryStrategy(str, Enum):
    RETRY = "retry"
    REASSIGN = "reassign"
    SPLIT = "split"
    RESTORE = "restore"
    REPLAN = "replan"
    ESCALATE = "escalate"


class RecoveryEngine:
    """Coordinates automated recovery workflows when tasks fail or contexts become stale."""

    def __init__(self, event_store: EventStore, project_id: str) -> None:
        self.event_store = event_store
        self.project_id = project_id

    def handle_failure(
        self,
        task_id: str,
        failure_type: str,
        details: Dict[str, Any],
        attempt_count: int = 1,
    ) -> RecoveryStrategy:
        """Determine and execute recovery strategy for a failed task or gate rejection."""
        self.event_store.append(
            actor="orchestrator",
            kind="recovery.started",
            project_id=self.project_id,
            task_id=task_id,
            payload={
                "failure_type": failure_type,
                "details": details,
                "attempt_count": attempt_count,
            },
        )

        strategy: RecoveryStrategy
        if failure_type in ("stale_context", "superseded_memory"):
            # Retry with recompiled fresh context
            strategy = RecoveryStrategy.RETRY if attempt_count <= 2 else RecoveryStrategy.REASSIGN

        elif failure_type == "syntax_build_failure":
            strategy = RecoveryStrategy.RETRY if attempt_count <= 2 else RecoveryStrategy.REASSIGN

        elif failure_type == "test_failure":
            if attempt_count == 1:
                strategy = RecoveryStrategy.RETRY
            elif attempt_count == 2:
                strategy = RecoveryStrategy.REASSIGN
            else:
                strategy = RecoveryStrategy.REPLAN

        elif failure_type == "security_violation":
            strategy = RecoveryStrategy.ESCALATE

        elif failure_type == "budget_exhausted":
            strategy = RecoveryStrategy.ESCALATE

        else:
            strategy = RecoveryStrategy.RETRY if attempt_count <= 2 else RecoveryStrategy.ESCALATE

        # Emit recovery action event
        event_kind = f"recovery.{strategy.value}"
        self.event_store.append(
            actor="orchestrator",
            kind=event_kind,
            project_id=self.project_id,
            task_id=task_id,
            payload={"strategy": strategy.value, "reason": failure_type},
        )

        return strategy
