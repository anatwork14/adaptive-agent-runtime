from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.codex_invocation_config import (
    CodexInvocationConfig,
    ConfigContractError,
    create_snapshot,
    stage_invocation_home,
    verify_snapshot,
    verify_staged_config,
)


def test_snapshot_serialization_is_deterministic_and_excludes_authentication(tmp_path: Path) -> None:
    first = create_snapshot(
        tmp_path / "a",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
        immutable=False,
    )
    second = create_snapshot(
        tmp_path / "b",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )

    assert first.snapshot_sha256 == second.snapshot_sha256
    assert (first.snapshot_path / "config.toml").read_bytes() == (
        second.snapshot_path / "config.toml"
    ).read_bytes()
    manifest = json.loads((first.snapshot_path / "config-manifest.json").read_text())
    assert manifest["scientific_fields"] == ["model", "model_reasoning_effort"]
    assert "runtime-only" not in json.dumps(manifest).lower()
    assert manifest["authentication_required"] is True


def test_snapshot_requires_exact_bytes_and_semantic_projection(tmp_path: Path) -> None:
    contract = create_snapshot(
        tmp_path / "snapshot",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )

    result = verify_snapshot(contract)

    assert result.status == "PASS"
    assert result.model == "gpt-5.5"
    assert result.reasoning == "high"


def test_missing_snapshot_fails_closed(tmp_path: Path) -> None:
    contract = CodexInvocationConfig(
        snapshot_path=tmp_path / "missing",
        snapshot_sha256="a" * 64,
        snapshot_size=1,
        codex_version="codex-cli 0.133.0-alpha.1",
        semantic_projection={"model": "gpt-5.5", "model_reasoning_effort": "high"},
    )

    with pytest.raises(ConfigContractError, match="snapshot bytes are missing"):
        verify_snapshot(contract)


def test_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    contract = create_snapshot(
        tmp_path / "snapshot",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
        immutable=False,
    )
    config_path = contract.snapshot_path / "config.toml"
    original = bytearray(config_path.read_bytes())
    original[-2] = ord("x")
    config_path.write_bytes(bytes(original))

    with pytest.raises(ConfigContractError, match="snapshot digest mismatch"):
        verify_snapshot(contract)


def test_two_snapshots_are_selected_explicitly(tmp_path: Path) -> None:
    high = create_snapshot(
        tmp_path / "high",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )
    medium = create_snapshot(
        tmp_path / "medium",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="medium",
    )

    assert verify_snapshot(high).reasoning == "high"
    assert verify_snapshot(medium).reasoning == "medium"
    assert high.snapshot_sha256 != medium.snapshot_sha256


def test_staging_copies_exact_config_and_runtime_only_auth(tmp_path: Path) -> None:
    contract = create_snapshot(
        tmp_path / "snapshot",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )
    auth_source = tmp_path / "authenticated-home" / "auth.json"
    auth_source.parent.mkdir()
    auth_source.write_text('{"credential":"runtime-only"}\n')

    with stage_invocation_home(contract, auth_source=auth_source) as staged:
        assert staged.environment["CODEX_HOME"] == str(staged.home)
        assert staged.config_path.read_bytes() == (contract.snapshot_path / "config.toml").read_bytes()
        assert staged.auth_path is not None
        assert staged.auth_path.read_bytes() == auth_source.read_bytes()
        assert verify_staged_config(contract, staged).status == "PASS"

    assert not staged.home.exists()


def test_staging_rejects_missing_auth_when_required(tmp_path: Path) -> None:
    contract = create_snapshot(
        tmp_path / "snapshot",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )

    with pytest.raises(ConfigContractError, match="authentication source is missing"):
        with stage_invocation_home(contract, auth_source=tmp_path / "missing-auth.json"):
            raise AssertionError("context must not yield")


def test_staged_corruption_fails_closed_before_provider_start(tmp_path: Path) -> None:
    contract = create_snapshot(
        tmp_path / "snapshot",
        codex_version="codex-cli 0.133.0-alpha.1",
        model="gpt-5.5",
        reasoning="high",
    )
    auth_source = tmp_path / "auth.json"
    auth_source.write_text("runtime credential placeholder\n")
    provider_starts = 0

    with stage_invocation_home(contract, auth_source=auth_source) as staged:
        corrupted = bytearray(staged.config_path.read_bytes())
        corrupted[-2] = ord("x")
        staged.config_path.write_bytes(bytes(corrupted))
        with pytest.raises(ConfigContractError, match="staged config identity mismatch"):
            verify_staged_config(contract, staged)

    assert provider_starts == 0
