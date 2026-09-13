"""Vendor-native authentication orchestration for ARC.

ARC deliberately never stores provider credentials. It delegates login/logout to
provider CLIs and only reports coarse authentication state.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

AuthProvider = Literal["codex", "claude", "antigravity"]


@dataclass(frozen=True)
class ProviderAuthSpec:
    provider: AuthProvider
    display_name: str
    executable: str
    login_command: tuple[str, ...]
    status_command: tuple[str, ...]
    logout_command: Optional[tuple[str, ...]]
    auth_method: str


@dataclass(frozen=True)
class ProviderAuthStatus:
    provider: str
    display_name: str
    installed: bool
    authenticated: bool
    state: str
    detail: str
    executable: Optional[str]
    auth_method: str


_PROVIDER_SPECS: dict[AuthProvider, ProviderAuthSpec] = {
    "codex": ProviderAuthSpec(
        provider="codex",
        display_name="OpenAI Codex",
        executable="codex",
        login_command=("codex", "login"),
        status_command=("codex", "login", "status"),
        logout_command=("codex", "logout"),
        auth_method="ChatGPT / OpenAI OAuth",
    ),
    "claude": ProviderAuthSpec(
        provider="claude",
        display_name="Claude Code",
        executable="claude",
        login_command=("claude", "auth", "login"),
        status_command=("claude", "auth", "status", "--text"),
        logout_command=("claude", "auth", "logout"),
        auth_method="Anthropic OAuth",
    ),
    "antigravity": ProviderAuthSpec(
        provider="antigravity",
        display_name="Antigravity",
        executable="agy",
        # Antigravity authenticates on first interactive launch.
        login_command=("agy",),
        # `agy models` is a non-destructive authenticated operation. A successful
        # result proves the CLI can reach the signed-in account without ARC
        # inspecting any credential files.
        status_command=("agy", "models"),
        logout_command=None,
        auth_method="Google OAuth",
    ),
}


def supported_auth_providers() -> list[ProviderAuthSpec]:
    return list(_PROVIDER_SPECS.values())


def get_auth_spec(provider: str) -> ProviderAuthSpec:
    key = provider.lower().strip()
    aliases = {"openai": "codex", "anthropic": "claude", "agy": "antigravity", "google": "antigravity"}
    key = aliases.get(key, key)
    if key not in _PROVIDER_SPECS:
        raise ValueError(f"Unsupported login provider: {provider}")
    return _PROVIDER_SPECS[key]  # type: ignore[index]


def _safe_detail(text: str, *, limit: int = 280) -> str:
    # Auth output should be status text, never secrets. Keep it short and strip
    # obvious bearer/key-looking fragments defensively before surfacing it.
    compact = " ".join((text or "").split())
    words = []
    for word in compact.split(" "):
        lowered = word.lower()
        if word.startswith(("sk-", "sess-", "ya29.")) or "bearer" in lowered:
            words.append("[redacted]")
        else:
            words.append(word)
    return " ".join(words)[:limit]


def _provider_environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    if environment:
        env.update({str(key): str(value) for key, value in environment.items()})
    return env


def auth_status(
    provider: str,
    *,
    timeout: float = 8.0,
    environment: Mapping[str, str] | None = None,
) -> ProviderAuthStatus:
    spec = get_auth_spec(provider)
    resolved = shutil.which(spec.executable)
    if not resolved:
        return ProviderAuthStatus(
            provider=spec.provider,
            display_name=spec.display_name,
            installed=False,
            authenticated=False,
            state="MISSING",
            detail=f"{spec.executable!r} is not installed or not on PATH",
            executable=None,
            auth_method=spec.auth_method,
        )

    env = _provider_environment(environment)
    if spec.provider == "antigravity":
        env.setdefault("TERM", "xterm-256color")
    try:
        result = subprocess.run(
            list(spec.status_command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ProviderAuthStatus(
            spec.provider,
            spec.display_name,
            True,
            False,
            "UNKNOWN",
            "authentication probe timed out",
            resolved,
            spec.auth_method,
        )

    output = _safe_detail(result.stdout or result.stderr)
    if result.returncode == 0:
        return ProviderAuthStatus(
            spec.provider,
            spec.display_name,
            True,
            True,
            "AUTHENTICATED",
            output or "provider CLI reports an authenticated session",
            resolved,
            spec.auth_method,
        )
    return ProviderAuthStatus(
        spec.provider,
        spec.display_name,
        True,
        False,
        "SIGNED_OUT",
        output or "provider CLI is installed but not authenticated",
        resolved,
        spec.auth_method,
    )


def login_provider(
    provider: str,
    *,
    cwd: str | Path = ".",
    environment: Mapping[str, str] | None = None,
) -> int:
    """Run the provider's native interactive login in the current terminal."""
    spec = get_auth_spec(provider)
    if shutil.which(spec.executable) is None:
        raise RuntimeError(f"{spec.display_name} CLI ({spec.executable}) is not installed")
    env = _provider_environment(environment)
    if spec.provider == "antigravity":
        env.setdefault("TERM", "xterm-256color")
    return subprocess.run(
        list(spec.login_command),
        cwd=str(Path(cwd).resolve()),
        env=env,
        check=False,
    ).returncode


def logout_provider(
    provider: str,
    *,
    cwd: str | Path = ".",
    environment: Mapping[str, str] | None = None,
) -> int:
    """Delegate logout to the provider. ARC never deletes credential files."""
    spec = get_auth_spec(provider)
    if spec.logout_command is None:
        raise RuntimeError(
            f"{spec.display_name} does not expose a stable logout command that ARC can safely delegate. "
            "Open the provider CLI and use its account controls instead; ARC will not delete vendor credential files."
        )
    if shutil.which(spec.executable) is None:
        raise RuntimeError(f"{spec.display_name} CLI ({spec.executable}) is not installed")
    return subprocess.run(
        list(spec.logout_command),
        cwd=str(Path(cwd).resolve()),
        env=_provider_environment(environment),
        check=False,
    ).returncode
