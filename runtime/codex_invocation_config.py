"""Immutable, invocation-scoped Codex configuration artifacts.

This module deliberately does not know how to authenticate a provider.  Codex
0.133.0-alpha.1 resolves both ``config.toml`` and file-backed ``auth.json``
from ``CODEX_HOME``.  ARC therefore keeps the scientific snapshot separate
from credentials and copies the latter only into a disposable invocation home.
The snapshot bytes and their digest remain the authority for configuration
identity.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import tomllib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONFIG_FILENAME = "config.toml"
SHA_FILENAME = "config.toml.sha256"
MANIFEST_FILENAME = "config-manifest.json"
DEFAULT_SCIENTIFIC_FIELDS = ("model", "model_reasoning_effort")


class ConfigContractError(RuntimeError):
    """Raised when an invocation configuration cannot be trusted."""


@dataclass(frozen=True)
class SnapshotVerification:
    status: str
    snapshot_path: Path
    config_sha256: str
    config_size: int
    model: str
    reasoning: str


@dataclass(frozen=True)
class CodexInvocationConfig:
    """Non-secret frozen identity for one Codex invocation configuration."""

    snapshot_path: Path
    snapshot_sha256: str
    snapshot_size: int
    codex_version: str
    semantic_projection: Mapping[str, Any]
    provider: str = "codex"
    authentication_required: bool = True

    @property
    def config_path(self) -> Path:
        return self.snapshot_path / CONFIG_FILENAME


@dataclass(frozen=True)
class StagedInvocationHome:
    """Disposable CODEX_HOME containing exact config bytes and runtime auth."""

    home: Path
    config_path: Path
    auth_path: Path | None
    environment: Mapping[str, str]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _toml_string(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) < 0x20 for char in value):
        raise ValueError("Codex config string values must be printable strings")
    return json.dumps(value, ensure_ascii=False)


def _canonical_config_bytes(fields: Mapping[str, Any]) -> bytes:
    """Serialize the supported flat scientific fields in sorted key order."""
    if set(fields) != set(DEFAULT_SCIENTIFIC_FIELDS):
        missing = sorted(set(DEFAULT_SCIENTIFIC_FIELDS) - set(fields))
        extra = sorted(set(fields) - set(DEFAULT_SCIENTIFIC_FIELDS))
        raise ValueError(f"unsupported scientific config shape: missing={missing}, extra={extra}")
    if any(not isinstance(value, str) for value in fields.values()):
        raise ValueError("minimal Codex scientific config values must be strings")
    lines = [f"{key} = {_toml_string(str(fields[key]))}" for key in sorted(fields)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_new(path: Path, payload: bytes, *, mode: int) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
    path.chmod(mode)


def create_snapshot(
    snapshot_path: str | Path,
    *,
    codex_version: str,
    model: str,
    reasoning: str,
    provider: str = "codex",
    authentication_required: bool = True,
    immutable: bool = True,
) -> CodexInvocationConfig:
    """Create a deterministic, non-secret scientific Codex snapshot.

    The snapshot contains only the two fields explicitly used by the V8/V9
    command contract.  Approval, sandbox, network, and trust policy remain
    caller-owned semantic fields until their pinned Codex representation is
    qualified; they are never guessed into this file.
    """
    root = Path(snapshot_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    config_bytes = _canonical_config_bytes(
        {"model": model, "model_reasoning_effort": reasoning}
    )
    digest = _sha256(config_bytes)
    config_path = root / CONFIG_FILENAME
    sha_path = root / SHA_FILENAME
    manifest_path = root / MANIFEST_FILENAME
    _write_new(config_path, config_bytes, mode=0o444 if immutable else 0o600)
    _write_new(sha_path, f"{digest}  {CONFIG_FILENAME}\n".encode("ascii"), mode=0o444)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "codex_version": codex_version,
        "provider": provider,
        "authentication_required": authentication_required,
        "credentials_in_snapshot": False,
        "config_sha256": digest,
        "config_size": len(config_bytes),
        "scientific_fields": list(DEFAULT_SCIENTIFIC_FIELDS),
        "semantic_projection": {
            "model": model,
            "model_reasoning_effort": reasoning,
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_new(manifest_path, manifest_bytes, mode=0o444)
    if immutable:
        root.chmod(0o555)
    return CodexInvocationConfig(
        snapshot_path=root,
        snapshot_sha256=digest,
        snapshot_size=len(config_bytes),
        codex_version=codex_version,
        semantic_projection=dict(manifest["semantic_projection"]),
        provider=provider,
        authentication_required=authentication_required,
    )


def verify_snapshot(contract: CodexInvocationConfig) -> SnapshotVerification:
    """Verify exact bytes, sidecar digest, manifest, and semantic projection."""
    root = contract.snapshot_path.expanduser().resolve()
    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        raise ConfigContractError("snapshot bytes are missing")
    raw = config_path.read_bytes()
    actual_digest = _sha256(raw)
    if len(raw) != contract.snapshot_size:
        raise ConfigContractError(
            f"snapshot size mismatch: expected={contract.snapshot_size}, actual={len(raw)}"
        )
    if actual_digest != contract.snapshot_sha256:
        raise ConfigContractError(
            f"snapshot digest mismatch: expected={contract.snapshot_sha256}, actual={actual_digest}"
        )
    sidecar = root / SHA_FILENAME
    expected_sidecar = f"{contract.snapshot_sha256}  {CONFIG_FILENAME}\n"
    if not sidecar.is_file() or sidecar.read_text(encoding="ascii") != expected_sidecar:
        raise ConfigContractError("snapshot digest sidecar mismatch")
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ConfigContractError("snapshot manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigContractError("snapshot manifest is invalid") from exc
    expected_projection = dict(contract.semantic_projection)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ConfigContractError("unsupported snapshot manifest schema")
    if manifest.get("codex_version") != contract.codex_version:
        raise ConfigContractError("snapshot Codex version mismatch")
    if manifest.get("provider") != contract.provider:
        raise ConfigContractError("snapshot provider mismatch")
    if manifest.get("config_sha256") != contract.snapshot_sha256:
        raise ConfigContractError("snapshot manifest digest mismatch")
    if manifest.get("config_size") != contract.snapshot_size:
        raise ConfigContractError("snapshot manifest size mismatch")
    if manifest.get("scientific_fields") != list(DEFAULT_SCIENTIFIC_FIELDS):
        raise ConfigContractError("snapshot scientific field declaration mismatch")
    if manifest.get("semantic_projection") != expected_projection:
        raise ConfigContractError("snapshot semantic projection mismatch")
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigContractError("snapshot config.toml is not valid UTF-8 TOML") from exc
    if parsed != expected_projection:
        raise ConfigContractError("snapshot TOML does not match semantic projection")
    model = parsed.get("model")
    reasoning = parsed.get("model_reasoning_effort")
    if not isinstance(model, str) or not isinstance(reasoning, str):
        raise ConfigContractError("snapshot model/reasoning fields are invalid")
    return SnapshotVerification(
        status="PASS",
        snapshot_path=root,
        config_sha256=actual_digest,
        config_size=len(raw),
        model=model,
        reasoning=reasoning,
    )


def verify_staged_config(
    contract: CodexInvocationConfig,
    staged: StagedInvocationHome,
) -> SnapshotVerification:
    """Recheck source and staged bytes immediately before process launch."""
    result = verify_snapshot(contract)
    if not staged.config_path.is_file():
        raise ConfigContractError("staged config is missing")
    staged_bytes = staged.config_path.read_bytes()
    staged_digest = _sha256(staged_bytes)
    if len(staged_bytes) != contract.snapshot_size or staged_digest != contract.snapshot_sha256:
        raise ConfigContractError(
            f"staged config identity mismatch: expected={contract.snapshot_sha256}, "
            f"actual={staged_digest}"
        )
    return result


@contextmanager
def stage_invocation_home(
    contract: CodexInvocationConfig,
    *,
    auth_source: str | Path | None,
) -> Iterator[StagedInvocationHome]:
    """Stage exact config bytes and runtime-only auth in a disposable home.

    Codex 0.133.0-alpha.1 has no supported separate auth-path override.  A
    runtime copy is therefore made only for the lifetime of this context. It
    is never part of the snapshot, manifest, digest, or preregistration.
    """
    verify_snapshot(contract)
    if contract.authentication_required:
        if auth_source is None:
            raise ConfigContractError("authentication source is missing")
        source_auth = Path(auth_source).expanduser().resolve()
        if not source_auth.is_file() or source_auth.is_symlink():
            raise ConfigContractError("authentication source is missing or unsupported")
    else:
        source_auth = None

    with tempfile.TemporaryDirectory(prefix="arc-codex-invocation-") as raw_home:
        home = Path(raw_home)
        home.chmod(0o700)
        config_path = home / CONFIG_FILENAME
        shutil.copyfile(contract.config_path, config_path)
        config_path.chmod(0o600)
        auth_path: Path | None = None
        if source_auth is not None:
            auth_path = home / "auth.json"
            shutil.copyfile(source_auth, auth_path)
            auth_path.chmod(0o600)
        staged = StagedInvocationHome(
            home=home,
            config_path=config_path,
            auth_path=auth_path,
            environment={"CODEX_HOME": str(home)},
        )
        verify_staged_config(contract, staged)
        yield staged


def is_owner_writable(path: Path) -> bool:
    """Expose the operational-immutability check without reading file content."""
    return bool(path.stat().st_mode & stat.S_IWUSR)
