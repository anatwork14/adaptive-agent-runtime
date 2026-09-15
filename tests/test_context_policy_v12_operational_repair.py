from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v12"
    / "production_state.py"
)
SPEC = importlib.util.spec_from_file_location("context_policy_v12_production_state", MODULE_PATH)
assert SPEC and SPEC.loader
v12 = importlib.util.module_from_spec(SPEC)
sys.modules["context_policy_v12_production_state"] = v12
SPEC.loader.exec_module(v12)


def evidence(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "provider_request_started": True,
        "provider_response_started": True,
        "provider_exit_code": 1,
        "provider_events": [
            {"type": "agent_message", "status": "completed"},
            {"type": "command_execution", "status": "completed", "exit_code": 0},
            {"type": "file_change", "status": "completed", "changes": ["x.py"]},
            {"type": "turn.failed", "message": "You've hit your usage limit."},
        ],
    }
    value.update(overrides)
    return value


def test_v11_usage_limit_is_provider_failure_even_after_side_effects() -> None:
    result = v12.classify_provider_evidence(evidence())
    assert result["provider_failure"] is True
    assert result["provider_error_class"] == "USAGE_LIMIT"
    assert result["terminal_state"] == "PROVIDER_CENSORED"
    assert result["safe_to_retry"] is False
    assert result["tool_execution_started"] is True
    assert result["repository_modified"] is True


def test_nonzero_exit_without_provider_evidence_is_not_provider_censor() -> None:
    result = v12.classify_provider_evidence(
        evidence(provider_events=[{"type": "agent_message", "status": "failed"}])
    )
    assert result["provider_failure"] is False
    assert result["terminal_state"] == "MODEL_FAILED"


@pytest.mark.parametrize(
    ("evidence_overrides", "expected"),
    [
        ({"timed_out": True, "provider_events": []}, "TIMEOUT"),
        ({"provider_events": [{"type": "error", "message": "connection reset"}]}, "PROVIDER_CENSORED"),
        ({"infrastructure_failure": True, "provider_events": []}, "INFRASTRUCTURE_FAILED"),
    ],
)
def test_provider_infrastructure_timeout_and_transport_precedence(
    evidence_overrides: dict[str, object], expected: str
) -> None:
    assert v12.classify_provider_evidence(evidence(**evidence_overrides))["terminal_state"] == expected


def test_authoritative_ledger_has_162_tasks_and_measurement_gate(tmp_path: Path) -> None:
    identities = v12.build_campaign_identities()
    assert len(identities) == 162
    with v12.ProductionLedger(tmp_path / "ledger.sqlite", campaign_id="context-policy-multirepo-v12", attempt_id="a001", expected_tasks=162) as ledger:
        ledger.register(identities)
        assert ledger.counts()["PENDING"] == 162
        identity = identities[0]
        instance = ledger.start_execution(identity, request_id="req-1", model="gpt-5.5", config_identity="frozen")
        with pytest.raises(ValueError, match="measurement"):
            ledger.complete_execution(identity, instance, measurement_ref=None)
        ledger.complete_execution(identity, instance, measurement_ref="measurements/T001.json")
        assert ledger.counts()["COMPLETED"] == 1
        assert ledger.counts()["PENDING"] == 161
        assert ledger.checkpoint()["next_schedulable_task"] == identities[1].key


def test_model_failure_is_preserved_and_next_task_continues(tmp_path: Path) -> None:
    identities = v12.build_fixture_identities(2)
    outcomes = [
        {"status": "model_failed", "exit_code": 1},
        {"status": "completed", "measurement_ref": "m/T002.json"},
    ]
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        runner.run(outcomes)
        assert runner.ledger.counts()["MODEL_FAILED"] == 1
        assert runner.ledger.counts()["COMPLETED"] == 1
        assert runner.provider_requests == 2


def test_side_effect_provider_censor_is_retained_and_not_retried(tmp_path: Path) -> None:
    identities = v12.build_fixture_identities(2)
    outcomes = [
        {"status": "provider_censored", "evidence": evidence()},
        {"status": "completed", "measurement_ref": "m/T002.json"},
    ]
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        runner.run(outcomes)
        assert runner.ledger.counts()["PROVIDER_CENSORED"] == 1
        assert runner.ledger.counts()["COMPLETED"] == 1
        assert len(runner.ledger.instances(identities[0])) == 1
        assert runner.ledger.resume_actions(provider_available=True)[identities[0].key] == "STOP_PROVIDER_CENSORED"


def test_safe_provider_censor_retry_keeps_both_instances(tmp_path: Path) -> None:
    identity = v12.build_fixture_identities(1)[0]
    with v12.ProductionLedger(tmp_path / "ledger.sqlite", campaign_id="fixture", attempt_id="a001", expected_tasks=1) as ledger:
        ledger.register([identity])
        first = ledger.start_execution(identity, request_id="req-1", model="gpt-5.5", config_identity="frozen")
        safe = evidence(provider_events=[{"type": "turn.failed", "message": "rate limit"}], provider_exit_code=1)
        ledger.censor_execution(identity, first, safe)
        assert ledger.resume_actions(provider_available=True)[identity.key] == "RETRY_PROVIDER_CENSORED"
        second = ledger.start_execution(identity, request_id="req-2", model="gpt-5.5", config_identity="frozen")
        ledger.complete_execution(identity, second, measurement_ref="m/T001-retry.json")
        assert [row["instance_id"] for row in ledger.instances(identity)] == [first, second]
        assert ledger.request_instance_count() == 2


def test_interruption_after_persistence_resumes_without_duplicate(tmp_path: Path) -> None:
    identities = v12.build_fixture_identities(5)
    outcomes = [{"status": "completed", "measurement_ref": f"m/{i}.json"} for i in range(5)]
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        with pytest.raises(v12.SimulatedInterruption):
            runner.run(outcomes, interrupt_after=4)
        assert runner.ledger.counts()["COMPLETED"] == 4
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as resumed:
        resumed.resume(outcomes)
        assert resumed.ledger.counts()["COMPLETED"] == 5
        assert resumed.provider_requests == 1
        assert all(len(resumed.ledger.instances(identity)) == 1 for identity in identities)


def test_crash_before_persistence_preserves_evidence_for_recovery(tmp_path: Path) -> None:
    identity = v12.build_fixture_identities(1)[0]
    evidence_dir = tmp_path / "evidence"
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=[identity], evidence_dir=evidence_dir) as runner:
        with pytest.raises(v12.SimulatedInterruption):
            runner.run([{"status": "completed", "measurement_ref": "m/T001.json"}], crash_before_persist=True)
        assert list(evidence_dir.glob("*.json"))
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=[identity], evidence_dir=evidence_dir) as resumed:
        resumed.recover_pending([{"status": "completed", "measurement_ref": "m/T001.json"}])
        assert resumed.ledger.counts()["COMPLETED"] == 1
        assert resumed.provider_requests == 0


def test_exact_v11_regression_persists_ledger_checkpoint_and_does_not_fail_fast(tmp_path: Path) -> None:
    identities = v12.build_fixture_identities(3)
    outcomes = [
        {"status": "completed", "measurement_ref": "m/T001.json"},
        {"status": "completed", "measurement_ref": "m/T002.json"},
        {"status": "provider_censored", "evidence": evidence()},
    ]
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        runner.run(outcomes)
        assert runner.ledger.counts()["PROVIDER_CENSORED"] == 1
        assert runner.ledger.counts()["COMPLETED"] == 2
        assert runner.ledger.checkpoint()["last_durable_transition"]
        assert runner.provider_requests == 3
        assert runner.legacy_fail_fast_triggered is False


def test_required_temporary_production_sequence_survives_interruption_and_resume(tmp_path: Path) -> None:
    identities = v12.build_fixture_identities(5)
    outcomes = [
        {"status": "completed", "measurement_ref": "m/T001.json"},
        {"status": "model_failed", "exit_code": 1},
        {"status": "provider_censored", "evidence": evidence()},
        {"status": "completed", "measurement_ref": "m/T004.json"},
        {"status": "completed", "measurement_ref": "m/T005.json"},
    ]
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        with pytest.raises(v12.SimulatedInterruption):
            runner.run(outcomes, interrupt_after=4)
        assert runner.ledger.counts() == {
            "PENDING": 1,
            "RUNNING": 0,
            "COMPLETED": 2,
            "PROVIDER_CENSORED": 1,
            "TIMEOUT": 0,
            "MODEL_FAILED": 1,
            "INFRASTRUCTURE_FAILED": 0,
        }
    with v12.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as resumed:
        resumed.resume(outcomes)
        assert resumed.ledger.counts()["COMPLETED"] == 3
        assert resumed.ledger.counts()["MODEL_FAILED"] == 1
        assert resumed.ledger.counts()["PROVIDER_CENSORED"] == 1
        assert resumed.provider_requests == 1
        assert resumed.legacy_fail_fast_triggered is False
