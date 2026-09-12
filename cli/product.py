"""Final installed ARC product surface for v0.6."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from cli.launcher import app
from tui.shell import run_shell
from webui.workspace_server import run_workspace


@app.command("ui")
def workspace_ui(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None),
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8788, min=1, max=65535),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the workspace in a browser"),
    allow_remote: bool = typer.Option(
        False,
        help="Allow non-loopback binding. ARC Workspace has no ARC-user authentication yet.",
    ),
) -> None:
    """Open the session-centric Agent Workspace UI."""
    try:
        run_workspace(
            repo=repo,
            project_id=project_id,
            host=host,
            port=port,
            allow_remote=allow_remote,
            open_browser=open_browser,
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


def main() -> None:
    """Launch conversational ARC by default; delegate explicit commands to Typer."""
    if len(sys.argv) == 1:
        run_shell(Path("."), None)
        return
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
