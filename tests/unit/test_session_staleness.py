"""Regression coverage for persistent-worker staleness semantics."""

from pathlib import Path

from context.staleness import StalenessDetector
from memory.lifecycle import MemoryLifecycle
from state.events import EventStore
from state.models import PatchSubmission


def test_own_session_events_do_not_self_invalidate_submission(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    try:
        store.append(actor="orchestrator", kind="project.created", project_id="demo", payload={})
        dispatch_v = store.current_version("demo")
        store.append(
            actor="operator",
            kind="session.message",
            project_id="demo",
            task_id="T001",
            correlation_id="S_test",
            payload={"session_id": "S_test", "role": "user", "content": "continue"},
        )
        store.append(
            actor="worker",
            kind="session.turn_finished",
            project_id="demo",
            task_id="T001",
            correlation_id="S_test",
            payload={"session_id": "S_test", "changed_files": ["src/a.py"]},
        )
        store.append(
            actor="orchestrator",
            kind="session.submitted",
            project_id="demo",
            task_id="T001",
            correlation_id="S_test",
            payload={"session_id": "S_test"},
        )
        detector = StalenessDetector(store, MemoryLifecycle(store))
        submission = PatchSubmission(
            patch_id="P1",
            task_id="T001",
            agent_id="worker",
            context_id="CTX1",
            dispatch_state_version=dispatch_v,
            candidate_commit_sha="a" * 40,
            candidate_branch="arc/task/T001",
            fencing_tokens=[],
            diff="",
            summary="session candidate",
            memories_used=[],
            decisions=[],
            assumptions=[],
        )
        assessment = detector.evaluate_submission(
            submission=submission,
            project_id="demo",
            dependency_task_ids=set(),
            declared_files={"src/a.py"},
        )
        assert assessment.staleness_score == 0.0
        assert assessment.relevant_delta_events == 0
        assert not assessment.is_stale
    finally:
        store.close()
