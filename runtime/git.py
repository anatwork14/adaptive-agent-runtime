"""Git argument helpers for ARC-created commit objects."""

from collections.abc import Sequence


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
