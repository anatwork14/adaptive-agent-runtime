"""Installed ARC CLI entrypoint with product UI surfaces attached."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from application.app import ArcApplication
from application.auth import (
    auth_status,
    get_auth_spec,
    login_provider,
    logout_provider,
    supported_auth_providers,
)
from application.config import AgentProfile
from cli.main import app
from tui.login import choose_login_provider

console = Console()
auth_app = typer.Typer(help="Sign in, sign out, and inspect vendor-native authentication.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")


def _brand() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]ARC[/bold cyan]  [bold]Adaptive Agent Runtime[/bold]\n"
            "[dim]Connect coding agents. Credentials stay with the provider CLI.[/dim]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _select_provider() -> str:
    selected = choose_login_provider()
    if not selected:
        raise typer.Exit(0)
    return selected


def _register_profile(repo: Path, provider: str, profile_name: Optional[str], make_default: bool) -> None:
    config_path = repo.resolve() / ".arc" / "config.yaml"
    if not config_path.exists():
        return
    name = profile_name or provider
    with ArcApplication(repo) as arc:
        arc.add_agent(
            AgentProfile(name=name, provider=provider, role="implementation"),  # type: ignore[arg-type]
            make_default=make_default,
        )
    suffix = " [default]" if make_default else ""
    console.print(f"[green]✓[/green] ARC profile [cyan]{name}[/cyan] configured{suffix}")


@app.command("login")
def login(
    provider: Optional[str] = typer.Argument(
        None, help="codex | claude | antigravity. Omit to open the interactive picker."
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="ARC profile name to create after login"),
    default: bool = typer.Option(False, "--default", help="Make the resulting ARC profile the default"),
    repo: Path = typer.Option(Path("."), help="Repository used for optional ARC profile registration"),
) -> None:
    """Sign in through the provider's own OAuth/account flow."""
    selected = provider or _select_provider()
    try:
        spec = get_auth_spec(selected)
        _brand()
        before = auth_status(spec.provider)
        if before.authenticated:
            console.print(f"[green]✓[/green] Already signed in to [bold]{spec.display_name}[/bold].")
            _register_profile(repo, spec.provider, profile, default)
            return
        if not before.installed:
            console.print(f"[red]×[/red] {before.detail}")
            raise typer.Exit(1)

        console.print(f"\n[bold]Signing in to {spec.display_name}[/bold]")
        console.print(f"[dim]{spec.auth_method} · ARC does not receive or store your credential.[/dim]\n")
        code = login_provider(spec.provider, cwd=repo)
        if code != 0:
            console.print(f"[red]Authentication command exited with code {code}.[/red]")
            raise typer.Exit(code)
        after = auth_status(spec.provider)
        if after.authenticated:
            console.print(f"\n[bold green]✓ Signed in[/bold green]  {after.detail}")
        else:
            console.print(
                "\n[yellow]Provider login returned successfully, but ARC could not confirm auth yet.[/yellow]\n"
                f"[dim]{after.detail}[/dim]"
            )
        _register_profile(repo, spec.provider, profile, default)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[bold red]ARC login error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command("logout")
def logout(
    provider: str = typer.Argument(..., help="codex | claude | antigravity"),
    repo: Path = typer.Option(Path("."), help="Working directory for the provider CLI"),
) -> None:
    """Log out through the provider CLI. ARC never deletes credential files itself."""
    try:
        spec = get_auth_spec(provider)
        _brand()
        console.print(f"Signing out of [bold]{spec.display_name}[/bold]…")
        code = logout_provider(spec.provider, cwd=repo)
        if code != 0:
            raise RuntimeError(f"provider logout exited with code {code}")
        console.print("[green]✓ Signed out[/green]")
    except Exception as exc:
        console.print(f"[bold red]ARC logout error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@auth_app.command("status")
def auth_status_command(
    provider: Optional[str] = typer.Argument(None, help="Optional provider; omit for all"),
) -> None:
    """Show provider installation and authentication state without exposing credentials."""
    _brand()
    providers = [get_auth_spec(provider)] if provider else supported_auth_providers()
    table = Table(title="Connected providers", box=box.SIMPLE_HEAVY)
    table.add_column("Provider", style="bold")
    table.add_column("CLI")
    table.add_column("Auth")
    table.add_column("State")
    table.add_column("Detail", ratio=2)
    for spec in providers:
        item = auth_status(spec.provider)
        color = "green" if item.authenticated else "yellow" if item.installed else "red"
        table.add_row(
            spec.display_name,
            item.executable or spec.executable,
            spec.auth_method,
            f"[{color}]{item.state}[/]",
            item.detail,
        )
    console.print(table)


@auth_app.command("login")
def auth_login(
    provider: Optional[str] = typer.Argument(None),
    profile: Optional[str] = typer.Option(None, "--profile"),
    default: bool = typer.Option(False, "--default"),
    repo: Path = typer.Option(Path(".")),
) -> None:
    """Alias for `arc login`."""
    login(provider=provider, profile=profile, default=default, repo=repo)


@auth_app.command("logout")
def auth_logout(
    provider: str = typer.Argument(...),
    repo: Path = typer.Option(Path(".")),
) -> None:
    """Alias for `arc logout`."""
    logout(provider=provider, repo=repo)


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
