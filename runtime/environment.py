"""Least-privilege environment construction for ARC-managed child processes.

Provider CLIs often authenticate through files/keyrings under HOME, but Python's
subprocess APIs inherit the *entire* parent environment unless ``env`` is passed.
ARC therefore constructs an explicit environment for coding agents, persistent
provider terminals, and worker previews. Repository-local config may opt in
additional environment variable *names*; ARC never stores the corresponding
values.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Process/runtime plumbing that is broadly required by CLIs and package tools.
# Deliberately excluded by default: SSH_AUTH_SOCK, cloud credentials, database
# URLs, arbitrary API keys, CI secrets, and provider keys for other vendors.
_BASE_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "COLORTERM",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        # Windows process/runtime plumbing. Harmlessly absent on POSIX.
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
    }
)

_PROVIDER_ENV_KEYS: dict[str, frozenset[str]] = {
    "mock": frozenset(),
    "codex": frozenset(
        {
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_ORGANIZATION",
            "OPENAI_PROJECT",
            "CODEX_HOME",
        }
    ),
    "claude": frozenset(
        {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "CLAUDE_CONFIG_DIR",
        }
    ),
    "antigravity": frozenset(
        {
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_CLOUD_PROJECT",
        }
    ),
    # OpenCode can broker several model providers. Keep this list explicit so a
    # user does not accidentally expose unrelated host secrets to the process.
    "opencode": frozenset(
        {
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
            "OPENROUTER_API_KEY",
        }
    ),
    "openrouter": frozenset({"OPENROUTER_API_KEY"}),
}

_SECRET_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "api-key",
    "credential",
    "private_key",
)

_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"\bsess-[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}"),
)


def validate_environment_name(name: str) -> str:
    """Validate and normalize an operator-configured environment variable name."""
    value = name.strip()
    if not value or not _ENV_NAME.fullmatch(value):
        raise ValueError(f"Invalid environment variable name: {name!r}")
    return value


def build_execution_environment(
    *,
    provider: str | None = None,
    extra_names: Iterable[str] = (),
    source: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the explicit environment passed to an ARC-managed child process.

    ``extra_names`` contains names only. Values are read at execution time from
    ``source`` (the live process environment by default), so secrets are never
    persisted to ARC config or events merely to make them available to a worker.
    """

    source_env = os.environ if source is None else source
    names = set(_BASE_ENV_KEYS)
    if provider:
        names.update(_PROVIDER_ENV_KEYS.get(provider.lower().strip(), frozenset()))
    names.update(validate_environment_name(name) for name in extra_names)
    environment = {name: str(source_env[name]) for name in sorted(names) if name in source_env}
    for raw_name, value in (overrides or {}).items():
        name = validate_environment_name(raw_name)
        environment[name] = str(value)
    return environment


def environment_key_manifest(environment: Mapping[str, str]) -> list[str]:
    """Return audit-safe environment metadata without values."""
    return sorted(environment)


def redact_command(command: Iterable[str]) -> list[str]:
    """Redact obvious secret-valued argv before recording a trace/event."""
    output: list[str] = []
    redact_next = False
    for raw in command:
        arg = str(raw)
        lower = arg.lower()
        if redact_next:
            output.append("<redacted>")
            redact_next = False
            continue
        if any(marker in lower for marker in _SECRET_MARKERS):
            if "=" in arg:
                output.append(arg.split("=", 1)[0] + "=<redacted>")
            else:
                output.append(arg)
                redact_next = True
            continue
        output.append(arg)
    return output


def redact_text_secrets(text: str, environment: Mapping[str, str] | None = None) -> str:
    """Remove obvious credential material before provider text becomes durable.

    Live provider output can include echoed environment variables, tool output,
    or authentication diagnostics. ARC redacts values of environment variables
    whose names are credential-like and also masks common provider token shapes.
    Non-secret runtime values such as HOME/PATH are intentionally preserved so
    logs remain useful for debugging.
    """
    output = str(text)
    for name, value in (environment or {}).items():
        if not value or len(value) < 4:
            continue
        lower = name.lower()
        if any(marker in lower for marker in _SECRET_MARKERS):
            output = output.replace(str(value), "<redacted>")
    for pattern in _TOKEN_PATTERNS:
        output = pattern.sub("<redacted>", output)
    return output
