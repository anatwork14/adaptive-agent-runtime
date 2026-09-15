"""Provider-free campaign integration checks for V10 Codex configuration."""

from pathlib import Path

import pytest

from adapters.codex import CodexAgentAdapter
from runtime.codex_invocation_config import (
    ConfigContractError,
    create_snapshot,
    load_snapshot,
    stage_invocation_home,
    verify_snapshot,
    verify_staged_config,
)

CODEX_VERSION = "codex-cli 0.133.0-alpha.1"


def _snapshot(root: Path, *, immutable: bool = False):
    return create_snapshot(
        root,
        codex_version=CODEX_VERSION,
        model="gpt-5.5",
        reasoning="high",
        provider="codex",
        immutable=immutable,
    )


def test_v10_config_gate_integration_cases(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path / "snapshot")
    auth = tmp_path / "auth.json"
    auth.write_text("runtime-only-auth-placeholder\n", encoding="utf-8")

    # A: valid snapshot, digest, manifest, and auth pass without inference.
    assert verify_snapshot(snapshot).status == "PASS"
    assert load_snapshot(snapshot.snapshot_path, expected_sha256=snapshot.snapshot_sha256)
    with stage_invocation_home(snapshot, auth_source=auth) as staged:
        assert verify_staged_config(snapshot, staged).status == "PASS"

    # B: changing a separate ambient file cannot affect the frozen source.
    ambient = tmp_path / "ambient-config.toml"
    ambient.write_text('model = "ambient-model"\n', encoding="utf-8")
    ambient.write_text('model = "different-ambient-model"\n', encoding="utf-8")
    assert verify_snapshot(snapshot).config_sha256 == snapshot.snapshot_sha256

    # C/D/E: source corruption, missing source, and staged corruption fail closed.
    corrupt = _snapshot(tmp_path / "corrupt")
    config_path = corrupt.config_path
    raw = bytearray(config_path.read_bytes())
    raw[-2] = ord("x")
    config_path.write_bytes(raw)
    with pytest.raises(ConfigContractError, match="snapshot digest mismatch"):
        verify_snapshot(corrupt)

    missing = _snapshot(tmp_path / "missing")
    missing.config_path.unlink()
    with pytest.raises(ConfigContractError, match="snapshot bytes are missing"):
        verify_snapshot(missing)

    with stage_invocation_home(snapshot, auth_source=auth) as staged:
        staged_raw = bytearray(staged.config_path.read_bytes())
        staged_raw[-2] = ord("x")
        staged.config_path.write_bytes(staged_raw)
        with pytest.raises(ConfigContractError, match="staged config identity mismatch"):
            verify_staged_config(snapshot, staged)

    # F: the configuration contract can pass while unavailable auth blocks staging.
    assert verify_snapshot(snapshot).status == "PASS"
    with pytest.raises(ConfigContractError, match="authentication source is missing"):
        with stage_invocation_home(snapshot, auth_source=tmp_path / "not-auth.json"):
            raise AssertionError("unavailable auth must not yield an invocation home")

    # G: the production adapter receives the immutable snapshot, not ambient config.
    adapter = CodexAgentAdapter(
        model_name="gpt-5.5",
        command_override="codex exec --full-auto --json -",
        codex_home=str(tmp_path / "auth-home"),
        invocation_config=snapshot,
        auth_source=auth,
    )
    with adapter._invocation_home() as invocation_home:
        assert Path(invocation_home, "config.toml").read_bytes() == snapshot.config_path.read_bytes()
        assert Path(invocation_home, "auth.json").read_bytes() == auth.read_bytes()


def test_v10_auth_is_never_part_of_snapshot_identity(tmp_path: Path) -> None:
    first = _snapshot(tmp_path / "first")
    second = _snapshot(tmp_path / "second")
    auth_a = tmp_path / "auth-a.json"
    auth_b = tmp_path / "auth-b.json"
    auth_a.write_text("credential-a\n", encoding="utf-8")
    auth_b.write_text("credential-b\n", encoding="utf-8")

    with stage_invocation_home(first, auth_source=auth_a) as staged_a:
        with stage_invocation_home(second, auth_source=auth_b) as staged_b:
            assert verify_staged_config(first, staged_a).config_sha256 == first.snapshot_sha256
            assert verify_staged_config(second, staged_b).config_sha256 == second.snapshot_sha256
    assert first.snapshot_sha256 == second.snapshot_sha256
