from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v13"
    / "production_state.py"
)
SPEC = importlib.util.spec_from_file_location("context_policy_v13_production_state", MODULE_PATH)
assert SPEC and SPEC.loader
v13 = importlib.util.module_from_spec(SPEC)
sys.modules["context_policy_v13_production_state"] = v13
SPEC.loader.exec_module(v13)


def _safe_censor() -> dict[str, object]:
    return {
        "provider_request_started": True,
        "provider_response_started": False,
        "provider_events": [{"type": "turn.failed", "message": "rate limit"}],
        "provider_exit_code": 1,
    }


def _unsafe_censor() -> dict[str, object]:
    return {
        "provider_request_started": True,
        "provider_response_started": True,
        "provider_events": [
            {"type": "agent_message", "status": "completed"},
            {"type": "turn.failed", "message": "rate limit"},
        ],
        "provider_exit_code": 1,
    }


def test_fake_provider_production_sequence_continues_and_resumes(tmp_path: Path) -> None:
    identities = v13.build_fixture_identities(5)
    outcomes = [
        {"status": "completed", "measurement_ref": "m/T001.json"},
        {"status": "model_failed", "exit_code": 1},
        {"status": "provider_censored", "evidence": _unsafe_censor()},
        {"status": "completed", "measurement_ref": "m/T004.json"},
        {"status": "completed", "measurement_ref": "m/T005.json"},
    ]

    with v13.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as runner:
        try:
            runner.run(outcomes, interrupt_after=4)
        except v13.SimulatedInterruption:
            pass
        assert runner.ledger.counts() == {
            "PENDING": 1,
            "RUNNING": 0,
            "COMPLETED": 2,
            "PROVIDER_CENSORED": 1,
            "TIMEOUT": 0,
            "MODEL_FAILED": 1,
            "INFRASTRUCTURE_FAILED": 0,
        }
        assert runner.ledger.request_instance_count() == 4
        assert runner.provider_requests == 4

    with v13.ProductionCampaignRunner(tmp_path / "ledger.sqlite", identities=identities) as resumed:
        resumed.resume(outcomes)
        assert resumed.ledger.counts()["COMPLETED"] == 3
        assert resumed.ledger.counts()["MODEL_FAILED"] == 1
        assert resumed.ledger.counts()["PROVIDER_CENSORED"] == 1
        assert resumed.provider_requests == 1
        assert all(len(resumed.ledger.instances(identity)) == 1 for identity in identities)


def test_provider_request_accounting_covers_pre_and_post_boundary_crashes(tmp_path: Path) -> None:
    identity = v13.build_fixture_identities(1)[0]
    ledger_path = tmp_path / "ledger.sqlite"
    with v13.ProductionLedger(
        ledger_path, campaign_id="fixture", attempt_id="a001", expected_tasks=1
    ) as ledger:
        ledger.register([identity])
        instance = ledger.start_execution(
            identity, request_id="pre-provider", model="gpt-5.5", config_identity="frozen"
        )
        assert ledger.provider_request_count() == 0
        assert ledger.recover_running() == {identity.key: "RECONCILE_PRE_PROVIDER_CRASH"}
        ledger.mark_provider_started(instance, identity=identity)
        assert ledger.provider_request_count() == 1
        assert ledger.recover_running() == {identity.key: "PRESERVE_AMBIGUOUS_PROVIDER_START"}
        assert ledger.request_instance_count() == 1


def test_safe_provider_censor_retry_is_registered_and_preserves_history(tmp_path: Path) -> None:
    identity = v13.build_fixture_identities(1)[0]
    with v13.ProductionLedger(
        tmp_path / "ledger.sqlite", campaign_id="fixture", attempt_id="a001", expected_tasks=1
    ) as ledger:
        ledger.register([identity])
        first = ledger.start_execution(
            identity, request_id="req-1", model="gpt-5.5", config_identity="frozen"
        )
        ledger.mark_provider_started(first, identity=identity)
        ledger.censor_execution(identity, first, _safe_censor())
        assert ledger.resume_actions(provider_available=True)[identity.key] == "RETRY_PROVIDER_CENSORED"
        second = ledger.start_execution(
            identity, request_id="req-2", model="gpt-5.5", config_identity="frozen"
        )
        ledger.mark_provider_started(second, identity=identity)
        ledger.complete_execution(identity, second, measurement_ref="m/T001-retry.json")
        assert ledger.request_instance_count() == 2
        assert len(ledger.instances(identity)) == 2
