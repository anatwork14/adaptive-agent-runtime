"""ARC package version helpers.

Keep product surfaces aligned with the installed distribution metadata rather
than copying release strings into each CLI or web application.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_DISTRIBUTION = "adaptive-agent-runtime"


def arc_version() -> str:
    """Return the installed ARC distribution version, or a source-tree fallback."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:
        return "0+unknown"
