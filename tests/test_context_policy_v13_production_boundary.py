from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

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


def test_v12_execution_boundary_regression_blocks_uninitialized_ledger(tmp_path: Path) -> None:
    ledger_path = tmp_path / "attempt" / "production-ledger.sqlite"
    manifest_path = tmp_path / "attempt" / "pre-execution-manifest.json"
    checkpoint_path = ledger_path
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")

    with v13.ProductionLedger(
        ledger_path,
        campaign_id="context-policy-multirepo-v13",
        attempt_id="a001",
        expected_tasks=162,
    ) as ledger:
        readiness = ledger.execution_boundary_snapshot(
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
        )
        assert readiness["logical_tasks"] == 0
        assert readiness["ready"] is False
        assert readiness["blocking_reason"] == "logical task ledger is not materialized"


def test_execution_boundary_is_ready_only_after_exact_preprovider_initialization(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "attempt" / "production-ledger.sqlite"
    manifest_path = tmp_path / "attempt" / "pre-execution-manifest.json"
    checkpoint_path = ledger_path
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")

    with v13.ProductionLedger(
        ledger_path,
        campaign_id="context-policy-multirepo-v13",
        attempt_id="a001",
        expected_tasks=162,
    ) as ledger:
        ledger.register(v13.build_campaign_identities())
        readiness = ledger.execution_boundary_snapshot(
            manifest_path=manifest_path,
            checkpoint_path=checkpoint_path,
        )
        assert readiness == {
            "ready": True,
            "logical_tasks": 162,
            "execution_instances": 0,
            "state_total": 162,
            "checkpoint": True,
            "pre_execution_manifest": True,
            "provider_requests": 0,
            "blocking_reason": None,
        }


def test_provider_request_requires_durable_instance_before_start(tmp_path: Path) -> None:
    identity = v13.build_fixture_identities(1)[0]
    with v13.ProductionLedger(
        tmp_path / "ledger.sqlite",
        campaign_id="fixture",
        attempt_id="a001",
        expected_tasks=1,
    ) as ledger:
        ledger.register([identity])
        instance = ledger.start_execution(
            identity,
            request_id="req-1",
            model="gpt-5.5",
            config_identity="frozen-v13",
        )
        assert ledger.instances(identity)[0]["provider_request_started"] == 0
        ledger.mark_provider_started(instance, identity=identity)
        assert ledger.instances(identity)[0]["provider_request_started"] == 1


@pytest.mark.parametrize("failure", ["ledger", "manifest", "checkpoint", "parity"])
def test_attempt_initialization_failures_block_before_provider(
    tmp_path: Path, failure: str
) -> None:
    with pytest.raises(v13.AttemptInitializationError):
        v13.initialize_production_attempt(
            ledger_path=tmp_path / "ledger.sqlite",
            manifest_path=tmp_path / "manifest.json",
            checkpoint_path=tmp_path / "checkpoint.json",
            identities=(
                v13.build_fixture_identities(1)
                if failure == "parity"
                else v13.build_campaign_identities()
            ),
            campaign_id="context-policy-multirepo-v13",
            attempt_id="a001",
            expected_tasks=162,
            manifest={"campaign": "context-policy-multirepo-v13"},
            fail_component=failure,
        )
