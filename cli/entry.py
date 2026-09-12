"""Installed ARC CLI entrypoint with product UI surfaces attached."""

from __future__ import annotations

import asyncio
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
from cli.main import agent_app, app
from tui.login import choose_login_provider

console = Console()
auth_app = typer.Typer(
    help="Sign in, sign out, and inspect vendor-native authentication.",
    no_args_is_help=True,
)
mission_app = typer.Typer(
    help="Plan an objective into a task DAG and execute it with the agent fleet.",
    no_args_is_help=True,
)
app.add_typer(auth_app, name="auth")
app.add_typer(mission_app, name="mission")


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


def _print_orchestration_result(result) -> None:
    color = "green" if result.successful else "yellow"
    console.print(
        Panel(
            f"run=[cyan]{result.run_id}[/cyan]  policy={result.policy}  rounds={result.rounds}\n"
            f"accepted=[green]{len(result.accepted)}[/green]  "
            f"rejected=[red]{len(result.rejected)}[/red]  "
            f"failed=[red]{len(result.failed)}[/red]  "
            f"deferred={len(set(result.deferred))}",
            title="ARC Orchestration",
            border_style=color,
        )
    )
    if result.routed:
        table = Table(title="Routing decisions", box=box.SIMPLE_HEAVY)
        table.add_column("Task", style="cyan")
        table.add_column("Agent", style="green")
        table.add_column("Score", justify="right")
        table.add_column("Why", ratio=3)
        for decision in result.routed:
            table.add_row(
                decision.task_id,
                decision.agent_name,
                f"{decision.score:.2f}",
                "; ".join(decision.reasons) or "policy score",
            )
        console.print(table)


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


@mission_app.command("plan")
def mission_plan(
    objective: str = typer.Argument(..., help="High-level objective to decompose"),
    file: list[str] = typer.Option([], "--file", help="Expected repository surface; repeatable"),
    accept: list[str] = typer.Option([], "--accept", help="Acceptance criterion; repeatable"),
    risk: float = typer.Option(0.5, min=0.0, max=1.0),
    tokens: int = typer.Option(24000, min=1000),
    max_tasks: int = typer.Option(8, min=1, max=32),
    run: bool = typer.Option(False, "--run", help="Immediately orchestrate the generated DAG"),
    policy: Optional[str] = typer.Option(None, help="balanced | quality | cost"),
    max_parallel: Optional[int] = typer.Option(None, min=1, max=32),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Turn one objective into a replayable task DAG."""
    try:
        with ArcApplication(repo, project_id) as arc:
            plan, tasks = arc.plan_objective(
                objective,
                files=file,
                acceptance=accept,
                risk=risk,
                token_budget=tokens,
                max_tasks=max_tasks,
            )
            table = Table(title=f"Mission plan // {plan.planner}", box=box.SIMPLE_HEAVY)
            table.add_column("Task", style="cyan")
            table.add_column("Type")
            table.add_column("Goal", ratio=3)
            table.add_column("Deps")
            table.add_column("Capabilities")
            for task in tasks:
                table.add_row(
                    task.task_id,
                    task.task_type,
                    task.goal,
                    ",".join(task.dependencies) or "-",
                    ",".join(task.required_capabilities) or "-",
                )
            console.print(table)
            if run:
                result = asyncio.run(
                    arc.orchestrate(policy=policy, max_parallel=max_parallel)
                )
                _print_orchestration_result(result)
    except Exception as exc:
        console.print(f"[bold red]ARC mission error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command("route")
def route_task(
    task_id: str = typer.Argument(...),
    policy: Optional[str] = typer.Option(None, help="balanced | quality | cost"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Explain which READY agent ARC would choose for a task."""
    try:
        with ArcApplication(repo, project_id) as arc:
            decision = arc.route_task(task_id, policy=policy)
            console.print(
                Panel(
                    f"task=[cyan]{task_id}[/cyan]\n"
                    f"agent=[green]{decision.agent_name}[/green]\n"
                    f"policy={decision.policy}  score={decision.score:.2f}\n\n"
                    + "\n".join(f"• {reason}" for reason in decision.reasons),
                    title="ARC Route Decision",
                    border_style="cyan",
                )
            )
    except Exception as exc:
        console.print(f"[bold red]ARC route error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command("orchestrate")
def orchestrate(
    policy: Optional[str] = typer.Option(None, help="balanced | quality | cost"),
    max_parallel: Optional[int] = typer.Option(None, min=1, max=32),
    max_rounds: int = typer.Option(100, min=1, max=1000),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Route and execute all currently reachable work until the DAG is idle."""
    try:
        with ArcApplication(repo, project_id) as arc:
            result = asyncio.run(
                arc.orchestrate(
                    policy=policy,
                    max_parallel=max_parallel,
                    max_rounds=max_rounds,
                )
            )
            _print_orchestration_result(result)
    except Exception as exc:
        console.print(f"[bold red]ARC orchestration error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@agent_app.command("tune")
def tune_agent_routing(
    name: str = typer.Argument(..., help="Existing agent profile"),
    capability: list[str] = typer.Option([], "--capability", help="Capability; repeatable"),
    role: Optional[str] = typer.Option(None),
    max_concurrency: Optional[int] = typer.Option(None, min=1, max=32),
    cost_weight: Optional[float] = typer.Option(None, min=0.0),
    quality_weight: Optional[float] = typer.Option(None, min=0.0),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Tune deterministic routing metadata without touching provider credentials."""
    try:
        with ArcApplication(repo, project_id) as arc:
            existing = arc.config.agents.get(name)
            if not existing:
                raise ValueError(f"Agent profile {name!r} not found")
            payload = existing.model_dump()
            if capability:
                payload["capabilities"] = capability
            if role is not None:
                payload["role"] = role
            if max_concurrency is not None:
                payload["max_concurrency"] = max_concurrency
            if cost_weight is not None:
                payload["cost_weight"] = cost_weight
            if quality_weight is not None:
                payload["quality_weight"] = quality_weight
            profile = AgentProfile.model_validate(payload)
            arc.add_agent(profile, make_default=arc.config.default_agent == name)
            console.print(
                f"[green]✓[/green] {name}: capabilities={','.join(profile.capabilities) or '-'} "
                f"max_concurrency={profile.max_concurrency} cost={profile.cost_weight:.2f} "
                f"quality={profile.quality_weight:.2f}"
            )
    except Exception as exc:
        console.print(f"[bold red]ARC tune error:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command("web")
def web_mission_control(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
    host: str = typer.Option("127.0.0.1", help="Bind host; localhost by default"),
    port: int = typer.Option(8787, min=1, max=65535),
    allow_remote: bool = typer.Option(
        False,
        "--allow-remote",
        help="Deprecated compatibility flag; remote binding remains disabled until ARC has authenticated remote mode.",
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