"""Unit tests for IntegrationGate."""

from runtime.gate import IntegrationGate
from state.events import EventStore
from state.models import GateStatus, PatchSubmission


def test_gate_accept_clean_patch(tmp_path):
    store = EventStore(tmp_path / "gate_test.db")
    gate = IntegrationGate(store, "p_gate", tmp_path, verification_level="V0")

    sub = PatchSubmission(
        patch_id="patch_1",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        diff="def foo(): return 42",
        summary="Added foo function",
    )

    result = gate.evaluate_submission(sub, staleness_score=0.1)
    assert result.status == GateStatus.ACCEPTED
    assert "G0_rebase" in result.stages_passed
    assert "G1_build_syntax" in result.stages_passed

    events = store.read_all(project_id="p_gate")
    kinds = [e.kind for e in events]
    assert "gate.started" in kinds
    assert "gate.accepted" in kinds
    store.close()


def test_gate_reject_stale_patch(tmp_path):
    store = EventStore(tmp_path / "gate_stale.db")
    gate = IntegrationGate(store, "p_gate", tmp_path, verification_level="V0")

    sub = PatchSubmission(
        patch_id="patch_stale",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        diff="def foo(): return 42",
        summary="Added foo",
    )

    result = gate.evaluate_submission(sub, staleness_score=0.95)
    assert result.status == GateStatus.REJECTED
    assert result.rejection_stage == "G0"
    assert "stale" in result.error_detail.lower()

    events = store.read_all(project_id="p_gate")
    kinds = [e.kind for e in events]
    assert "gate.c0_failed" in kinds
    assert "gate.rejected" in kinds
    store.close()


def test_gate_reject_security_violation_in_v2(tmp_path):
    store = EventStore(tmp_path / "gate_sec.db")
    gate = IntegrationGate(store, "p_gate", tmp_path, verification_level="V2")

    sub = PatchSubmission(
        patch_id="patch_leak",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        diff='api_key = "ghp_123456789012345678901234567890123456"',
        summary="Hardcoded token",
    )

    result = gate.evaluate_submission(sub, staleness_score=0.0)
    assert result.status == GateStatus.REJECTED
    assert result.rejection_stage == "V2"
    assert "security" in result.error_detail.lower()
    store.close()
