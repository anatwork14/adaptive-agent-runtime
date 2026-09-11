"""Unit tests for RecoveryEngine."""

from runtime.recovery import RecoveryEngine, RecoveryStrategy
from state.events import EventStore


def test_recovery_workflow_and_escalation(tmp_path):
    store = EventStore(tmp_path / "rec.db")
    engine = RecoveryEngine(store, "p_rec")

    # Stale context at attempt 1 -> retry
    strat1 = engine.handle_failure("t1", "stale_context", {"version_lag": 5}, attempt_count=1)
    assert strat1 == RecoveryStrategy.RETRY

    # Security violation -> escalate
    strat2 = engine.handle_failure("t1", "security_violation", {}, attempt_count=1)
    assert strat2 == RecoveryStrategy.ESCALATE

    events = store.read_all(project_id="p_rec")
    kinds = [e.kind for e in events]
    assert "recovery.started" in kinds
    assert "recovery.retry" in kinds
    assert "recovery.escalate" in kinds

    store.close()
