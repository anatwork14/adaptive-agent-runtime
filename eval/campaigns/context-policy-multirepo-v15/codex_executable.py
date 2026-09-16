"""Fail-closed identity checks for the V15 Codex executable."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CodexExecutableIdentityError(RuntimeError):
    """The executable does not match the frozen campaign identity."""


@dataclass(frozen=True)
class CodexExecutableIdentity:
    path: Path
    version: str
    sha256: str
    architecture: str


def inspect_codex_executable(
    path: str | Path,
    *,
    expected_version: str,
    expected_sha256: str,
    expected_architecture: str,
) -> CodexExecutableIdentity:
    executable = Path(path).expanduser().resolve()
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise CodexExecutableIdentityError(
            f"Codex executable is missing or not executable: {executable}"
        )
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise CodexExecutableIdentityError(
            f"Codex executable SHA256 mismatch: expected={expected_sha256}, actual={digest}"
        )
    version_result = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version_lines = (version_result.stdout or version_result.stderr).strip().splitlines()
    actual_version = version_lines[0].strip() if version_lines else ""
    if version_result.returncode != 0 or actual_version != expected_version:
        raise CodexExecutableIdentityError(
            f"Codex executable version mismatch: expected={expected_version}, actual={actual_version!r}"
        )
    file_result = subprocess.run(
        ["file", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    description = (file_result.stdout or "").strip()
    architecture = platform.machine()
    if (
        file_result.returncode != 0
        or expected_architecture not in description
        or architecture != expected_architecture
    ):
        raise CodexExecutableIdentityError(
            f"Codex executable architecture mismatch: expected={expected_architecture}, "
            f"host={architecture}, file={description!r}"
        )
    return CodexExecutableIdentity(
        path=executable,
        version=actual_version,
        sha256=digest,
        architecture=architecture,
    )
