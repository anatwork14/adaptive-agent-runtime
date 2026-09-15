import json
from pathlib import Path

import pytest

from application.agents import profile_invocation_config
from application.config import AgentProfile
from runtime.codex_invocation_config import ConfigContractError, load_snapshot

CAMPAIGN = Path(__file__).parents[2] / "eval" / "campaigns" / "context-policy-multirepo-v11"
SNAPSHOT = CAMPAIGN / "codex"


def _complete_profile() -> AgentProfile:
    snapshot = load_snapshot(SNAPSHOT)
    return AgentProfile(
        name="builder",
        provider="codex",
        model="gpt-5.5",
        codex_home="/Users/teobun/arc-secure/codex-v8-home",
        codex_config_path=str(snapshot.config_path),
        codex_invocation_snapshot_path=str(snapshot.snapshot_path),
        codex_invocation_snapshot_sha256=snapshot.snapshot_sha256,
        codex_invocation_snapshot_size=snapshot.snapshot_size,
        codex_invocation_manifest_path=str(snapshot.manifest_path),
        codex_invocation_manifest_sha256=snapshot.manifest_sha256,
        codex_invocation_codex_version=snapshot.codex_version,
        codex_invocation_provider=snapshot.provider,
        codex_invocation_authentication_required=snapshot.authentication_required,
        codex_invocation_semantic_projection=dict(snapshot.semantic_projection),
    )


def test_profile_round_trip_reconstructs_the_same_canonical_contract():
    profile = _complete_profile()
    restored = AgentProfile.model_validate(profile.model_dump(mode="json"))
    actual = profile_invocation_config(restored, require_complete=True)
    expected = load_snapshot(SNAPSHOT)

    assert actual == expected


@pytest.mark.parametrize(
    "field",
    [
        "codex_invocation_snapshot_path",
        "codex_invocation_snapshot_sha256",
        "codex_invocation_snapshot_size",
        "codex_invocation_manifest_path",
        "codex_invocation_manifest_sha256",
        "codex_invocation_codex_version",
        "codex_invocation_provider",
        "codex_invocation_authentication_required",
        "codex_invocation_semantic_projection",
    ],
)
def test_incomplete_profile_fails_closed(field):
    profile = _complete_profile()
    value = {} if field == "codex_invocation_semantic_projection" else None
    incomplete = profile.model_copy(update={field: value})

    with pytest.raises(ConfigContractError, match="incomplete"):
        profile_invocation_config(incomplete, require_complete=True)


def test_v10_profile_shape_is_an_exact_regression_failure():
    profile = _complete_profile().model_copy(
        update={
            "codex_invocation_snapshot_size": None,
            "codex_invocation_manifest_path": None,
            "codex_invocation_manifest_sha256": None,
            "codex_invocation_codex_version": None,
            "codex_invocation_provider": None,
            "codex_invocation_authentication_required": None,
            "codex_invocation_semantic_projection": {},
        }
    )

    with pytest.raises(ConfigContractError):
        profile_invocation_config(profile, require_complete=True)


def test_campaign_contract_declares_the_same_snapshot_identity():
    contract = json.loads((CAMPAIGN / "campaign_contract.json").read_text(encoding="utf-8"))
    profile = _complete_profile()
    actual = profile_invocation_config(profile, require_complete=True)
    declared = contract["provider_profile"]

    assert str(actual.snapshot_path) == declared["codex_invocation_snapshot_path"]
    assert actual.snapshot_sha256 == declared["codex_invocation_snapshot_sha256"]
    assert actual.snapshot_size == declared["codex_invocation_snapshot_size"]
    assert str(actual.manifest_path) == declared["codex_invocation_manifest_path"]
    assert actual.manifest_sha256 == declared["codex_invocation_manifest_sha256"]
    assert actual.codex_version == declared["codex_invocation_codex_version"]
    assert actual.provider == declared["codex_invocation_provider"]
    assert actual.authentication_required == declared["codex_invocation_authentication_required"]
    assert dict(actual.semantic_projection) == declared["codex_invocation_semantic_projection"]
