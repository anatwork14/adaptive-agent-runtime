from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).parents[1]
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v14"
    / "codex_executable.py"
)
SPEC = importlib.util.spec_from_file_location("context_policy_v14_codex_executable", MODULE_PATH)
assert SPEC and SPEC.loader
codex_executable = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = codex_executable
SPEC.loader.exec_module(codex_executable)


PINNED_PATH = Path(
    "/Users/teobun/arc-secure/codex-v0.133.0-alpha.1/codex-aarch64-apple-darwin"
)
PINNED_VERSION = "codex-cli 0.133.0-alpha.1"
PINNED_SHA256 = "fcde55f63e03b1d0d368789007c709f629a118c959c25eec5db15235b8b312af"


def test_pinned_executable_identity_matches_path_version_hash_and_architecture() -> None:
    identity = codex_executable.inspect_codex_executable(
        PINNED_PATH,
        expected_version=PINNED_VERSION,
        expected_sha256=PINNED_SHA256,
        expected_architecture="arm64",
    )
    assert identity.path == PINNED_PATH.resolve()
    assert identity.version == PINNED_VERSION
    assert identity.sha256 == PINNED_SHA256
    assert identity.architecture == "arm64"


def test_wrong_version_fails_closed_without_provider_request() -> None:
    with pytest.raises(codex_executable.CodexExecutableIdentityError, match="version mismatch"):
        codex_executable.inspect_codex_executable(
            PINNED_PATH,
            expected_version="codex-cli 0.154.0",
            expected_sha256=PINNED_SHA256,
            expected_architecture="arm64",
        )


def test_wrong_hash_fails_closed_without_provider_request() -> None:
    with pytest.raises(codex_executable.CodexExecutableIdentityError, match="SHA256 mismatch"):
        codex_executable.inspect_codex_executable(
            PINNED_PATH,
            expected_version=PINNED_VERSION,
            expected_sha256="0" * 64,
            expected_architecture="arm64",
        )
