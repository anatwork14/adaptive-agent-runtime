"""Installed ARC launcher with conversation-first defaults and session controls."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Importing cli.entry registers the complete v0.5 command surface on this Typer app.
from cli.entry import app
from application.session_app import SessionArcApplication
from tui.shell import run_shell

console = Console()
session_app = typer.Typer(
    help="Open, converse with, inspect, resume, and submit persistent coding workers.",
    no_args_is_help=True,
)
app.add_typer(session_app, name="session")


def _open(repo: Path, project_id: Optional[str]) -> SessionArcApplication:
    return SessionArcApplication(repo, project_id)


def _fail(message: str) -> None:
    console.print(f"[bold red]ARC error:[/bold red] {message}")
    raise typer.Exit(1)


def _session_table(sessions) -> Table:
    table = Table(title="Worker sessions", box=box.SIMPLE_HEAVY)
    table.add_column("Session", style="cyan")
    table.add_column("Task", style="bold")
    table.add_column("Agent", style="green")
    table.add_column("Provider")
    table.add_column("State")
    table.add_column("Files", justify="right")
    table.add_column("Last message", ratio=2)
    for session in sessions:
        last = session.messages[-1].content if session.messages else ""
        if len(last) > 70:
            last = last[:67] + "..."
        table.add_row(
            session.session_id,
            session.task_id,
            session.agent_name,
            session.provider,
            session.status.value,
            str(len(session.changed_files)),
            last,
        )
    return table


@app.command("shell")
def shell(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Open the conversation-first ARC supervisor explicitly."""
    run_shell(repo, project_id)


@session_app.command("open")
def session_open(
    task_id: str = typer.Argument(..., help="READY task to own interactively"),
    agent: Optional[str] = typer.Option(None, help="Named agent profile; omit for routing"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Open a persistent worker with an isolated worktree."""
    try:
        with _open(repo, project_id) as arc:
            session = arc.sessions.create(task_id, agent_name=agent)
            console.print(
                Panel(
                    f"session=[cyan]{session.session_id}[/cyan]\n"
                    f"task={session.task_id}  agent=[green]{session.agent_name}[/green]  "
                    f"provider={session.provider}\n"
                    f"workspace={session.worktree_path}\n"
                    f"branch={session.branch}\n\n"
                    f"Continue: [bold]arc session send {session.session_id} \"instruction\"[/bold]\n"
                    f"Native UI: [bold]arc attach {session.session_id}[/bold]",
                    title="ARC worker opened",
                    border_style="cyan",
                )
            )
    except Exception as exc:
        _fail(str(exc))


@session_app.command("list")
def session_list(
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """List persistent workers reconstructed from authoritative events."""
    try:
        with _open(repo, project_id) as arc:
            console.print(_session_table(arc.sessions.list()))
    except Exception as exc:
        _fail(str(exc))


@session_app.command("show")
def session_show(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Show worker metadata and recent conversation."""
    try:
        with _open(repo, project_id) as arc:
            session = arc.sessions.get(session_id)
            if not session:
                _fail(f"Worker session {session_id} not found")
            lines = [
                f"task: {session.task_id}",
                f"agent: {session.agent_name} ({session.provider})",
                f"state: {session.status.value}",
                f"terminal: {session.terminal_state}",
                f"branch: {session.branch}",
                f"workspace: {session.worktree_path}",
                f"context: {session.context_id} @ state v{session.dispatch_state_version}",
            ]
            console.print(Panel("\n".join(lines), title=session.session_id, border_style="cyan"))
            for message in session.messages[-12:]:
                style = "bold white" if message.role == "user" else "cyan" if message.role == "assistant" else "dim"
                console.print(f"[{style}]{message.role}>[/] {message.content}")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@session_app.command("send")
def session_send(
    session_id: str,
    instruction: str = typer.Argument(..., help="Next instruction for the worker"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Continue a worker conversation in its existing worktree."""
    try:
        with _open(repo, project_id) as arc:
            before = arc.sessions.get(session_id)
            if not before:
                _fail(f"Worker session {session_id} not found")
            console.print(f"[yellow]{before.agent_name} working…[/yellow]")
            session = asyncio.run(arc.sessions.send(session_id, instruction))
            assistant = next(
                (message for message in reversed(session.messages) if message.role == "assistant"),
                None,
            )
            if assistant:
                console.print(Panel(assistant.content, title=session.agent_name, border_style="cyan"))
            changed = arc.sessions.changed_files(session_id)
            if changed:
                console.print("Changed: " + ", ".join(changed))
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@session_app.command("files")
def session_files(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """List files changed in a worker's persistent draft workspace."""
    try:
        with _open(repo, project_id) as arc:
            files = arc.sessions.changed_files(session_id)
            console.print("\n".join(files) if files else "No changes yet.")
    except Exception as exc:
        _fail(str(exc))


@session_app.command("diff")
def session_diff(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Show the current unsubmitted worker diff."""
    try:
        with _open(repo, project_id) as arc:
            console.print(arc.sessions.diff(session_id) or "No changes yet.", markup=False)
    except Exception as exc:
        _fail(str(exc))


@session_app.command("submit")
def session_submit(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Freeze the draft candidate and run ARC's transactional integration gate."""
    try:
        with _open(repo, project_id) as arc:
            result = asyncio.run(arc.sessions.submit(session_id))
            color = "green" if result.status.value == "accepted" else "red"
            console.print(
                Panel(
                    f"status=[{color}]{result.status.value}[/]\n"
                    f"gate={result.gate_run_id}\n"
                    f"merged={result.merged_commit_sha or '-'}\n"
                    f"stages={', '.join(result.stages_passed) or '-'}",
                    title=f"Submit // {session_id}",
                    border_style=color,
                )
            )
    except Exception as exc:
        _fail(str(exc))


@session_app.command("stop")
def session_stop(
    session_id: str,
    reason: str = typer.Option("operator stopped worker"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Discard a draft workspace and return its task to the READY frontier."""
    try:
        with _open(repo, project_id) as arc:
            session = arc.sessions.stop(session_id, reason=reason)
            console.print(f"[yellow]{session.session_id}[/yellow] → {session.status.value}")
    except Exception as exc:
        _fail(str(exc))


@session_app.command("resume")
def session_resume(
    session_id: str,
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Re-attach ARC to a persisted worker/worktree after restarting the CLI."""
    try:
        with _open(repo, project_id) as arc:
            session = arc.sessions.resume(session_id)
            console.print(
                f"[green]Resumed[/green] {session.session_id}  "
                f"workspace={session.worktree_path}"
            )
    except Exception as exc:
        _fail(str(exc))


@app.command("attach")
def attach_native_terminal(
    session_id: str = typer.Argument(..., help="Worker session to attach"),
    repo: Path = typer.Option(Path(".")),
    project_id: Optional[str] = typer.Option(None),
) -> None:
    """Open the provider's native terminal UI inside the worker worktree.

    ARC suspends supervision while the provider owns the terminal, then records
    the resulting changed-file surface when the native UI exits. Credentials and
    provider-native session behavior remain owned by the vendor CLI.
    """
    try:
        arc = _open(repo, project_id)
        try:
            session = arc.sessions.get(session_id)
            if not session:
                _fail(f"Worker session {session_id} not found")
            command = arc.sessions.native_command(session_id)
            if shutil.which(command[0]) is None:
                _fail(f"Provider executable {command[0]!r} was not found")
            workspace = Path(session.worktree_path)
            if not workspace.exists():
                _fail(f"Worker workspace is missing: {workspace}")
            arc.sessions.mark_terminal(session_id, live=True)
            console.print(
                f"[dim]ARC → native {session.provider} terminal · {session.task_id} · {workspace}[/dim]"
            )
            try:
                code = subprocess.run(command, cwd=str(workspace), check=False).returncode
            finally:
                arc.sessions.mark_terminal(session_id, live=False)
                changed = arc.sessions.changed_files(session_id)
                arc.event_store.append(
                    actor=session.agent_name,
                    kind="session.turn_finished",
                    project_id=arc.project_id,
                    task_id=session.task_id,
                    correlation_id=session_id,
                    payload={
                        "session_id": session_id,
                        "changed_files": changed,
                        "native_terminal": True,
                    },
                )
            if code != 0:
                console.print(f"[yellow]Native provider exited with code {code}.[/yellow]")
        finally:
            arc.close()
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


def main() -> None:
    """Installed console entrypoint.

    Plain `arc` launches the interactive supervisor; any arguments are delegated
    to the full Typer command surface for automation and scripting.
    """
    if len(sys.argv) == 1:
        run_shell(Path("."), None)
        return
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
