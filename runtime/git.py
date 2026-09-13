"""Git argument and environment helpers for ARC-created commit objects."""

import os
from collections.abc import Mapping, Sequence

_IDENTITY_ENV_KEYS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


def arc_git_write_args(
    args: Sequence[str],
    *,
    user_name: str,
    user_email: str,
) -> list[str]:
    """Prefix an ARC-controlled commit operation with hermetic Git settings.

    ARC must not let a user's global signing configuration turn a candidate or
    gate operation into an interactive host-dependent action. These are
    command-level settings, so they do not mutate repository or global config.
    """
    if not args:
        raise ValueError("ARC Git write command cannot be empty")
    return [
        "-c",
        f"user.name={user_name}",
        "-c",
        f"user.email={user_email}",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]


def arc_git_write_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a Git-write environment without inherited identity overrides.

    Git identity environment variables take precedence over command-scoped
    ``user.name``/``user.email`` settings. ARC therefore removes only those
    four variables for its own commit-producing subprocesses. The returned
    mapping is a copy; neither the caller's environment nor Git configuration
    is mutated.
    """
    environment = dict(os.environ if source is None else source)
    for key in _IDENTITY_ENV_KEYS:
        environment.pop(key, None)
    return environment
