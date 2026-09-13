"""Static V4 timeout-contract checks that do not freeze or execute a campaign."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

CAMPAIGN_DIR = Path(__file__).parents[2] / "eval" / "campaigns" / "context-policy-multirepo-v4"


def _freeze_module():
    path = CAMPAIGN_DIR / "freeze_campaign.py"
    spec = importlib.util.spec_from_file_location("v4_freeze_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v4_contract_changes_only_the_provider_execution_timeout() -> None:
    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))

    assert contract["campaign_id"] == "context-policy-multirepo-v4"
    assert contract["parent_campaign"] == "context-policy-multirepo-v3"
    assert contract["scientific_core_preserved"] is True
    assert contract["protocol_change"] == "provider execution timeout"
    assert contract["treatment_neutral"] is True
    assert contract["shared_protocol"]["provider_execution_timeout_seconds"] == 600
    assert contract["provider_runtime"]["provider_execution_timeout_seconds"] == 600
    assert contract["provider_runtime"]["codex_home"] == "/Users/teobun/arc-secure/codex-v4-home"
    assert contract["provider_runtime"]["codex_config_path"] == (
        "/Users/teobun/arc-secure/codex-v4-home/config.toml"
    )
    assert contract["provider_runtime"]["codex_config_sha256"] == (
        "1981d54e8058aa36da3bb6a2b5e7babfd3784f3904d5dd320074426d193172d5"
    )
    assert "CODEX_HOME" in contract["provider_runtime"]["environment_allowlist"]["observed_keys"]
    assert {
        repository["visible_test_harness"]["timeout_seconds"]
        for repository in contract["repositories"].values()
    } == {180}


def test_v4_applies_one_provider_timeout_to_every_treatment_and_no_retry() -> None:
    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))
    assert set(contract["treatments"]) == {"B3", "B5", "B7"}
    assert contract["provider_execution_policy"] == {
        "timeout_seconds": 600,
        "applies_to": ["B3", "B5", "B7"],
        "per_task_override": False,
        "per_repetition_override": False,
        "dynamic_extension": False,
        "retry_on_timeout": False,
    }


def test_v4_protocol_diff_separates_timeout_from_codex_home_apparatus_change() -> None:
    diff = json.loads((CAMPAIGN_DIR / "v3_to_v4_protocol_diff.json").read_text(encoding="utf-8"))
    assert diff["scientific_core_preserved"] is True
    assert diff["treatment_neutral"] is True
    assert diff["apparatus_changes"] == [
        {
            "field": "provider_runtime.codex_home",
            "reason": "isolate the frozen provider CLI from mutable user-level Codex/router configuration",
        },
        {
            "field": "provider_runtime.codex_config_sha256",
            "reason": "cryptographically bind non-secret provider configuration",
        },
    ]


def test_freeze_timeout_guard_rejects_drift_before_any_freeze_output() -> None:
    contract = json.loads((CAMPAIGN_DIR / "campaign_contract.json").read_text(encoding="utf-8"))
    drifted = copy.deepcopy(contract)
    drifted["shared_protocol"]["provider_execution_timeout_seconds"] = 599

    with pytest.raises(SystemExit, match="exactly 600"):
        _freeze_module()._validate_timeout_contract(drifted)
