"""Installed ARC CLI entrypoint with optional UI surfaces attached."""

from pathlib import Path
from typing import Optional

import typer

from cli.main import app


@app.command("web")
def web_mission_control(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
    host: str = typer.Option("127.0.0.1", help="Bind host; localhost by default"),
    port: int = typer.Option(8787, min=1, max=65535),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Allow binding beyond loopback. The current web UI has no authentication.",
    ),
    open_browser: bool = typer.Option(False, "--open", help="Open the browser after starting"),
) -> None:
    """Launch the localhost ARC browser Mission Control."""
    from webui.server import run_web

    try:
        run_web(
            repo=repo,
            project_id=project_id,
            host=host,
            port=port,
            allow_remote=allow_remote,
            open_browser=open_browser,
        )
    except Exception as exc:
        typer.echo(f"ARC web error: {exc}", err=True)
        raise typer.Exit(1) from exc


__all__ = ["app"]
