"""Fail-closed identity and source-cleanliness checks for the V15 launcher."""

from __future__ import annotations

import hashlib
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class LauncherIdentityError(RuntimeError):
    """The qualified V15 launcher environment does not match its frozen identity."""


class SourceRepositoryMutationError(RuntimeError):
    """The persistent ARC source repository was mutated by launcher machinery."""


@dataclass(frozen=True)
class PythonLauncherIdentity:
    path: Path
    version: str
    sha256: str
    architecture: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_python_executable(
    path: str | Path,
    *,
    expected_version: str,
    expected_sha256: str,
    expected_architecture: str,
) -> PythonLauncherIdentity:
    executable = Path(path).expanduser().resolve()
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise LauncherIdentityError(f"qualified Python executable is not executable: {executable}")
    actual_sha256 = _sha256(executable)
    if actual_sha256 != expected_sha256:
        raise LauncherIdentityError(
            f"Python executable SHA256 mismatch: expected={expected_sha256}, actual={actual_sha256}"
        )
    result = subprocess.run(
        [str(executable), "-c", "import platform, sys; print(sys.version.split()[0]); print(platform.machine())"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LauncherIdentityError(result.stderr.strip() or "Python identity probe failed")
    lines = result.stdout.splitlines()
    if len(lines) < 2:
        raise LauncherIdentityError("Python identity probe returned incomplete output")
    version, architecture = lines[0].strip(), lines[1].strip()
    if version != expected_version:
        raise LauncherIdentityError(
            f"Python version mismatch: expected={expected_version}, actual={version}"
        )
    if architecture != expected_architecture:
        raise LauncherIdentityError(
            f"Python architecture mismatch: expected={expected_architecture}, actual={architecture}"
        )
    return PythonLauncherIdentity(executable, version, actual_sha256, architecture)


def assert_source_repository_clean(repository: str | Path, *, stage: str) -> None:
    path = Path(repository).expanduser().resolve()
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SourceRepositoryMutationError(
            f"cannot inspect source repository at {stage}: {result.stderr.strip()}"
        )
    if result.stdout.strip():
        raise SourceRepositoryMutationError(
            f"source repository mutated at {stage}: {result.stdout.strip()}"
        )


def build_launcher_argv(
    python_executable: str | Path,
    runner: str | Path,
    arguments: Sequence[str],
) -> list[str]:
    """Build the canonical direct-Python command; never route through uv."""
    python = str(Path(python_executable))
    runner_path = str(Path(runner))
    if Path(python).name.startswith("uv") or Path(runner_path).name == "uv":
        raise LauncherIdentityError("V15 launcher cannot use uv as its Python executable")
    return [python, runner_path, *arguments]
