"""Installed ARC product surface for interactive supervision, reviews, and live runtimes."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from application.session_app import SessionArcApplication
from cli.launcher import app, session_app
from tui.shell import run_shell
from webui.workspace_server import run_workspace

console = Console()


def _open(repo: Path, project_id: Optional[str]) -> SessionArcApplication:
    return SessionArcApplication(repo, project_id)


def _review_panel(status) -> Panel:
    checks = status.checks
    failed = len(status.failed_checks)
    pending = len(status.pending_checks)
    body = (
        f"PR: {status.pr_url or '-'}\n"
        f"state: {status.state or '-'}  review: {status.review_decision or '-'}  "
        f"merge: {status.merge_state_status or '-'}\n"
        f"checks: {len(checks)} total · {failed} failed · {pending} pending\n"
        f"feedback: {'pending' if status.pending_feedback else 'none'}"
    )
    border = "green" if status.healthy else "yellow" if status.linked else "dim"
    return Panel(body, title=f"GitHub review // {status.session_id}", border_style=border)


def _runtime_panel(state) -> Panel:
    body = (
        f"backend={state.backend}\n"
        f"runtime={state.runtime_name}\n"
        f"running={state.running}  ready={state.ready}\n"
        f"workspace={state.workspace}\n"
    )
    if state.url:
        body += f"url={state.url}\n"
    if state.command:
        body += "command=" + " ".join(state.command)
    color = "green" if state.ready else "yellow" if state.running else "dim"
    return Panel(body.rstrip(), title=f"{state.kind} // {state.session_id}", border_style=color)


@app.command("ui")
def workspace_ui(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None),
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8788, min=1, max=65535),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the workspace in a browser"),
    allow_remote: bool = typer.Option(
        False,
        help="Deprecated compatibility flag; remote binding remains disabled until ARC has authenticated remote mode.",
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


@session_app.command("publish")
def publish_session_pr(
    session_id: str = typer.Argument(..., help="Persistent worker session"),
    base: str = typer.Option("main", help="Pull-request base branch"),
    remote: str = typer.Option("origin", help="Git remote used for the review branch"),
    title: Optional[str] = typer.Option(None, help="Optional pull-request title"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Commit the current worker draft, push its branch, and create/update its PR."""
    try:
        with _open(repo, project_id) as arc:
            doctor = arc.reviews.doctor()
            if doctor["status"] != "READY":
                raise typer.BadParameter(
                    f"GitHub integration is {doctor['status']}: {doctor['detail']}"
                )
            status = arc.reviews.publish(
                session_id,
                base=base,
                remote=remote,
                title=title,
            )
            console.print(_review_panel(status))
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@session_app.command("review")
def sync_session_review(
    session_id: str = typer.Argument(..., help="Persistent worker session"),
    apply: bool = typer.Option(
        False,
        "--apply/--no-apply",
        help="Immediately send new actionable CI/review feedback back to the worker",
    ),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Refresh GitHub checks/reviews and optionally apply new feedback to the worker."""
    try:
        with _open(repo, project_id) as arc:
            result = asyncio.run(arc.reviews.sync(session_id, auto_apply=apply))
            console.print(_review_panel(result.status))
            if result.changed:
                console.print("[cyan]Review state changed and was recorded in ARC events.[/cyan]")
            else:
                console.print("[dim]No GitHub review-state change.[/dim]")
            if result.feedback_applied:
                console.print("[green]New actionable feedback was routed to the worker.[/green]")
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("supervise")
def supervise_reviews(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None),
    interval: float = typer.Option(30.0, min=5.0, help="GitHub review polling interval in seconds"),
    auto_apply: bool = typer.Option(
        False,
        "--auto-apply/--no-auto-apply",
        help="Automatically route new actionable review/CI feedback into linked workers",
    ),
    once: bool = typer.Option(False, help="Run one review synchronization pass and exit"),
) -> None:
    """Supervise all PR-linked workers and keep external review state synchronized."""
    try:
        arc = _open(repo, project_id)
        try:
            doctor = arc.reviews.doctor()
            if doctor["status"] != "READY":
                raise typer.BadParameter(
                    f"GitHub integration is {doctor['status']}: {doctor['detail']}"
                )
            console.print(
                Panel(
                    f"project={arc.project_id}\ninterval={interval:.0f}s\n"
                    f"auto_apply={auto_apply}\n\n"
                    "GitHub remains an external review surface; ARC events/tasks remain authoritative.",
                    title="ARC review supervisor",
                    border_style="cyan",
                )
            )
            if once:
                results = asyncio.run(arc.reviews.supervise_once(auto_apply=auto_apply))
                table = Table("Session", "PR", "Changed", "Feedback", "Error")
                for item in results:
                    table.add_row(
                        item.session_id,
                        str(item.status.pr_number or "-"),
                        "yes" if item.changed else "no",
                        "applied" if item.feedback_applied else (
                            "pending" if item.status.pending_feedback else "none"
                        ),
                        item.error or "",
                    )
                console.print(table)
                return
            try:
                asyncio.run(
                    arc.reviews.supervise(
                        interval_seconds=interval,
                        auto_apply=auto_apply,
                    )
                )
            except KeyboardInterrupt:
                console.print("\n[dim]Review supervisor stopped.[/dim]")
        finally:
            arc.close()
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command("terminal")
def persistent_terminal(
    session_id: str = typer.Argument(..., help="Worker session to attach in persistent tmux mode"),
    start_only: bool = typer.Option(
        False,
        "--start-only/--attach",
        help="Start persistent provider terminal without attaching the current shell",
    ),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Start or reattach a provider terminal that survives the invoking ARC process."""
    arc = _open(repo, project_id)
    try:
        doctor = arc.worker_runtime.doctor()
        if doctor["status"] != "READY":
            raise typer.BadParameter(f"Persistent runtime is {doctor['status']}: {doctor['detail']}")
        state = arc.worker_runtime.start_terminal(session_id)
        console.print(_runtime_panel(state))
        if start_only:
            console.print(
                f"[dim]Reattach later with: arc terminal {session_id}[/dim]"
            )
            return
        code = arc.worker_runtime.attach_terminal(session_id)
        if code != 0:
            console.print(f"[yellow]tmux attach exited with code {code}[/yellow]")
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc
    finally:
        arc.close()


@session_app.command("terminal-status")
def terminal_status(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Inspect persistent provider-terminal state and recent terminal output."""
    try:
        with _open(repo, project_id) as arc:
            state = arc.worker_runtime.status(session_id, "terminal")
            console.print(_runtime_panel(state))
            if state.log_tail:
                console.print(Panel(state.log_tail[-12000:], title="Terminal tail", border_style="dim"))
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@session_app.command("terminal-stop")
def terminal_stop(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Stop the tmux-owned provider terminal for a worker."""
    try:
        with _open(repo, project_id) as arc:
            console.print(_runtime_panel(arc.worker_runtime.stop_terminal(session_id)))
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@session_app.command("preview-start")
def preview_start(
    session_id: str,
    command: str = typer.Option(
        ...,
        help="Command template containing {host} and {port}, e.g. 'npm run dev -- --host {host} --port {port}'",
    ),
    port: int = typer.Option(..., min=1, max=65535),
    host: str = typer.Option("127.0.0.1", help="Loopback host used by the preview server"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Start a persistent localhost preview process inside the worker worktree."""
    try:
        with _open(repo, project_id) as arc:
            doctor = arc.worker_runtime.doctor()
            if doctor["status"] != "READY":
                raise typer.BadParameter(
                    f"Persistent runtime is {doctor['status']}: {doctor['detail']}"
                )
            state = arc.worker_runtime.start_preview(
                session_id,
                command_template=command,
                port=port,
                host=host,
            )
            console.print(_runtime_panel(state))
            console.print("[dim]The process is tmux-owned and survives this ARC CLI process exiting.[/dim]")
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@session_app.command("preview-status")
def preview_status(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Inspect worker preview liveness/readiness and recent server output."""
    try:
        with _open(repo, project_id) as arc:
            state = arc.worker_runtime.status(session_id, "preview")
            console.print(_runtime_panel(state))
            if state.log_tail:
                console.print(Panel(state.log_tail[-12000:], title="Preview log tail", border_style="dim"))
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc


@session_app.command("preview-stop")
def preview_stop(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Stop the persistent worker preview process."""
    try:
        with _open(repo, project_id) as arc:
            console.print(_runtime_panel(arc.worker_runtime.stop_preview(session_id)))
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