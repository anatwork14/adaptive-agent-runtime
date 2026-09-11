"""ARC CLI v2 — operator interface for the shared application service layer."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from application.app import ArcApplication
from application.config import AgentProfile
from runtime.replay import ReplayEngine
from state.models import TaskStatus

app = typer.Typer(
    name="arc",
    help="ARC — reliable context control and mission control for coding agents",
    add_completion=False,
    no_args_is_help=True,
)
task_app = typer.Typer(help="Create, inspect, execute, retry, and cancel tasks.", no_args_is_help=True)
agent_app = typer.Typer(help="Configure and diagnose named coding-agent profiles.", no_args_is_help=True)
memory_app = typer.Typer(help="Inspect and manage the Adaptive Memory Plane.", no_args_is_help=True)
context_app = typer.Typer(help="Compile and inspect immutable Context Packets.", no_args_is_help=True)
gate_app = typer.Typer(help="Inspect transactional integration-gate activity.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect repository-local ARC configuration.", no_args_is_help=True)
eval_app = typer.Typer(help="Evaluation commands (research workbench).", no_args_is_help=True)

app.add_typer(task_app, name="task")
app.add_typer(agent_app, name="agent")
app.add_typer(memory_app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(gate_app, name="gate")
app.add_typer(config_app, name="config")
app.add_typer(eval_app, name="eval")

console = Console()


def _arc(repo: Path, project_id: Optional[str]) -> ArcApplication:
    return ArcApplication(repo, project_id)


def _fail(message: str) -> None:
    console.print(f"[bold red]ARC error:[/bold red] {message}")
    raise typer.Exit(1)


def _status_style(status: str) -> str:
    return {
        "ready": "cyan",
        "dispatched": "yellow",
        "submitted": "yellow",
        "completed": "green",
        "failed": "red",
        "blocked": "red",
        "abandoned": "dim",
        "created": "blue",
    }.get(status, "white")


def _task_table(tasks) -> Table:
    table = Table(title="Task DAG", box=box.SIMPLE_HEAVY, header_style="bold magenta")
    table.add_column("Task", style="bold cyan", no_wrap=True)
    table.add_column("Goal", ratio=3)
    table.add_column("Status", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Deps", no_wrap=True)
    table.add_column("Risk", justify="right")
    table.add_column("Attempts", justify="right")
    for task in tasks:
        table.add_row(
            task.task_id,
            task.goal,
            f"[{_status_style(task.status.value)}]{task.status.value}[/]",
            task.assigned_agent or "-",
            ",".join(task.dependencies) or "-",
            f"{task.risk:.2f}",
            str(task.attempt_count),
        )
    return table


def _events_table(events, *, title: str = "Authoritative events") -> Table:
    table = Table(title=title, box=box.SIMPLE, header_style="bold")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Actor", style="yellow", no_wrap=True)
    table.add_column("Kind", style="green", no_wrap=True)
    table.add_column("Task", style="magenta", no_wrap=True)
    table.add_column("Payload", ratio=2)
    for event in events:
        payload = json.dumps(event.payload, ensure_ascii=False)
        if len(payload) > 90:
            payload = payload[:87] + "..."
        table.add_row(
            str(event.id),
            event.ts[11:19] if len(event.ts) >= 19 else event.ts,
            event.actor,
            event.kind,
            event.task_id or "-",
            payload,
        )
    return table


@app.command()
def init(
    repo: Path = typer.Argument(Path("."), help="Git repository to initialize"),
    project_id: str = typer.Option("default", help="Project identifier"),
) -> None:
    """Initialize ARC state and a repository-local configuration file."""
    try:
        with _arc(repo, project_id) as arc:
            event_id = arc.initialize()
            console.print(
                f"[bold green]ARC initialized[/bold green] in [cyan]{arc.arc_dir}[/cyan] "
                f"(project={project_id}, event={event_id})"
            )
            console.print("Default agent profile: [cyan]mock[/cyan] (zero-credential smoke tests)")
    except Exception as exc:  # CLI boundary
        _fail(str(exc))


@app.command()
def status(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier; defaults to config"),
) -> None:
    """Show authoritative project state, budget, leases, agents, and task DAG."""
    try:
        with _arc(repo, project_id) as arc:
            snap = arc.snapshot()
            budget = snap["budget"]
            console.rule(f"[bold]ARC // {snap['project_id']} // STATE v{snap['version']}[/bold]")
            console.print(
                f"Budget: [cyan]${budget.consumed_usd:.2f}[/cyan] / ${budget.hard_project_ceiling_usd:.2f}  "
                f"Tokens: [cyan]{budget.consumed_tokens:,}[/cyan]  "
                f"Active leases: [cyan]{len(snap['leases'])}[/cyan]  "
                f"Agents: [cyan]{len(snap['agents'])}[/cyan]"
            )
            console.print(_task_table(snap["tasks"]))
    except Exception as exc:
        _fail(str(exc))


@app.command()
def events(
    after: int = typer.Option(0, help="Show events strictly after this ID"),
    limit: int = typer.Option(50, min=1, max=1000),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Inspect the append-only authoritative event stream."""
    try:
        with _arc(repo, project_id) as arc:
            console.print(_events_table(arc.recent_events(after=after, limit=limit)))
    except Exception as exc:
        _fail(str(exc))


@app.command()
def replay(
    upto: Optional[int] = typer.Option(None, help="Replay up to event ID"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Rebuild deterministic projections from authoritative events."""
    try:
        with _arc(repo, project_id) as arc:
            arc.require_initialized()
            projection = ReplayEngine(arc.event_store).replay_project(
                arc.project_id, upto_event_id=upto
            )
            console.print(
                f"[bold green]Replay successful[/bold green] — state v{projection.version}, "
                f"tasks={len(projection.dag.tasks)}, completed={len(projection.project.state.completed_tasks)}, "
                f"cost=${projection.budgets.state.consumed_usd:.2f}"
            )
    except Exception as exc:
        _fail(str(exc))


@app.command("run")
def run_task_root(
    task_id: str = typer.Argument(..., help="Task to execute"),
    agent: Optional[str] = typer.Option(None, help="Named agent profile; defaults to config"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Execute one READY task through context → worktree → candidate → gate."""
    _run_task(task_id, agent, repo, project_id)


@task_app.command("create")
def task_create(
    goal: str = typer.Argument(..., help="Task goal"),
    task_id: Optional[str] = typer.Option(None, "--id", help="Explicit task ID; auto-generates T001..."),
    dependency: list[str] = typer.Option([], "--depends", help="Dependency task ID; repeatable"),
    file: list[str] = typer.Option([], "--file", help="Declared file surface; repeatable"),
    symbol: list[str] = typer.Option([], "--symbol", help="Relevant symbol; repeatable"),
    accept: list[str] = typer.Option([], "--accept", help="Acceptance criterion; repeatable"),
    risk: float = typer.Option(0.5, min=0.0, max=1.0),
    tokens: int = typer.Option(24000, min=1000, help="Context token ceiling"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Create a versioned task in the authoritative DAG."""
    try:
        with _arc(repo, project_id) as arc:
            task = arc.create_task(
                goal,
                task_id=task_id,
                dependencies=dependency,
                files=file,
                symbols=symbol,
                acceptance=accept,
                risk=risk,
                token_budget=tokens,
            )
            console.print(
                f"[bold green]Created[/bold green] [cyan]{task.task_id}[/cyan] "
                f"status={task.status.value} risk={task.risk:.2f} tokens={task.token_budget}"
            )
    except Exception as exc:
        _fail(str(exc))


@task_app.command("list")
def task_list(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """List all tasks in the current project DAG."""
    try:
        with _arc(repo, project_id) as arc:
            arc.require_initialized()
            console.print(_task_table(arc.list_tasks()))
    except Exception as exc:
        _fail(str(exc))


@task_app.command("show")
def task_show(
    task_id: str,
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Show one task, its execution metadata, and recent authoritative events."""
    try:
        with _arc(repo, project_id) as arc:
            task = arc.get_task(task_id)
            if not task:
                _fail(f"Task {task_id} not found")
            lines = [
                f"[bold]{task.goal}[/bold]",
                f"status: [{_status_style(task.status.value)}]{task.status.value}[/]",
                f"agent: {task.assigned_agent or '-'}   attempts: {task.attempt_count}   risk: {task.risk:.2f}",
                f"dependencies: {', '.join(task.dependencies) or '-'}",
                f"files: {', '.join(task.files_declared) or '-'}",
                f"acceptance: {'; '.join(task.acceptance_criteria) or '-'}",
                f"token ceiling: {task.token_budget:,}",
            ]
            console.print(Panel("\n".join(lines), title=f"Task {task.task_id}", border_style="cyan"))
            console.print(_events_table(arc.task_events(task_id, limit=20), title="Task event trail"))
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@task_app.command("run")
def task_run(
    task_id: str,
    agent: Optional[str] = typer.Option(None, help="Named agent profile"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Execute a READY task. Alias of `arc run`."""
    _run_task(task_id, agent, repo, project_id)


def _run_task(task_id: str, agent: Optional[str], repo: Path, project_id: Optional[str]) -> None:
    try:
        with _arc(repo, project_id) as arc:
            profile_name = agent or arc.config.default_agent
            console.print(f"[bold]ARC mission[/bold] {task_id} → [cyan]{profile_name}[/cyan]")
            result = asyncio.run(arc.run_task(task_id, agent_name=profile_name))
            color = "green" if result.status.value == "accepted" else "red"
            console.print(
                Panel(
                    f"status=[{color}]{result.status.value}[/]  "
                    f"gate={result.gate_run_id}  merged={result.merged_commit_sha or '-'}\n"
                    f"stages={', '.join(result.stages_passed) or '-'}",
                    title=f"Gate result // {task_id}",
                    border_style=color,
                )
            )
            console.print(_events_table(arc.task_events(task_id, limit=14), title="Mission event trail"))
    except Exception as exc:
        _fail(str(exc))


@task_app.command("retry")
def task_retry(
    task_id: str,
    reason: str = typer.Option("manual retry"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Move a failed/blocked task back to READY through recovery.retry."""
    try:
        with _arc(repo, project_id) as arc:
            task = arc.retry_task(task_id, reason=reason)
            console.print(f"[green]{task.task_id}[/green] → {task.status.value}")
    except Exception as exc:
        _fail(str(exc))


@task_app.command("cancel")
def task_cancel(
    task_id: str,
    reason: str = typer.Option("operator cancelled"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Authoritatively abandon an unfinished task."""
    try:
        with _arc(repo, project_id) as arc:
            task = arc.cancel_task(task_id, reason=reason)
            console.print(f"[yellow]{task.task_id}[/yellow] → {task.status.value}")
    except Exception as exc:
        _fail(str(exc))


@app.command()
def watch(
    task_id: str = typer.Argument(..., help="Task to monitor"),
    interval: float = typer.Option(0.5, min=0.1, help="Refresh interval in seconds"),
    timeout: float = typer.Option(0.0, min=0.0, help="Stop after N seconds; 0 means unlimited"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Live mission view backed by the authoritative event stream."""
    terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ABANDONED}
    try:
        with _arc(repo, project_id) as arc:
            arc.require_initialized()
            if not arc.get_task(task_id):
                _fail(f"Task {task_id} not found")
            started = time.monotonic()
            with Live(console=console, refresh_per_second=max(2, int(1 / interval)), screen=False) as live:
                while True:
                    task = arc.get_task(task_id)
                    assert task is not None
                    events = arc.task_events(task_id, limit=12)
                    state = Text()
                    state.append(f"{task.task_id}  ", style="bold cyan")
                    state.append(task.status.value, style=_status_style(task.status.value))
                    state.append(f"   agent={task.assigned_agent or '-'}   attempt={task.attempt_count}   risk={task.risk:.2f}")
                    live.update(
                        Group(
                            Panel(state, title="ARC // live mission", border_style="cyan"),
                            _events_table(events, title="Latest events"),
                        )
                    )
                    if task.status in terminal:
                        break
                    if timeout and time.monotonic() - started >= timeout:
                        break
                    time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]watch stopped[/dim]")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@agent_app.command("list")
def agent_list(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """List named agent profiles."""
    try:
        with _arc(repo, project_id) as arc:
            table = Table(title="Agent profiles", box=box.SIMPLE_HEAVY)
            table.add_column("Name", style="cyan")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Role")
            table.add_column("Default")
            table.add_column("Enabled")
            for profile in arc.list_agents():
                table.add_row(
                    profile.name,
                    profile.provider,
                    profile.model or "-",
                    profile.role,
                    "●" if arc.config.default_agent == profile.name else "",
                    "yes" if profile.enabled else "no",
                )
            console.print(table)
    except Exception as exc:
        _fail(str(exc))


@agent_app.command("add")
def agent_add(
    name: str = typer.Argument(..., help="Profile name"),
    provider: str = typer.Option(..., help="mock|codex|claude|opencode|openrouter"),
    model: Optional[str] = typer.Option(None),
    role: str = typer.Option("implementation"),
    command: Optional[str] = typer.Option(None, help="Provider command override"),
    default: bool = typer.Option(False, "--default", help="Make this the default profile"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Add or replace a named agent profile."""
    try:
        with _arc(repo, project_id) as arc:
            profile = AgentProfile(
                name=name,
                provider=provider,
                model=model,
                role=role,
                command_override=command,
            )
            arc.add_agent(profile, make_default=default)
            console.print(
                f"[green]Saved[/green] {name}: provider={profile.provider} model={profile.model or '-'} role={profile.role}"
            )
    except Exception as exc:
        _fail(str(exc))


@agent_app.command("remove")
def agent_remove(
    name: str,
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Remove a named profile (the built-in mock profile is retained)."""
    try:
        with _arc(repo, project_id) as arc:
            arc.config = arc.config_store.remove_agent(name)
            console.print(f"[yellow]Removed[/yellow] {name}")
    except Exception as exc:
        _fail(str(exc))


@agent_app.command("doctor")
def agent_doctor(
    names: list[str] = typer.Argument(None, help="Optional profile names; defaults to all"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Check provider executables and execution readiness without running an agent."""
    try:
        with _arc(repo, project_id) as arc:
            rows = arc.doctor_agents(names or None)
            table = Table(title="ARC agent doctor", box=box.SIMPLE_HEAVY)
            table.add_column("Name", style="cyan")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Status")
            table.add_column("Detail", ratio=2)
            for row in rows:
                color = "green" if row.status == "READY" else "yellow" if row.status == "GATEWAY_ONLY" else "red"
                table.add_row(
                    row.name,
                    row.provider,
                    row.model or "-",
                    f"[{color}]{row.status}[/]",
                    row.detail,
                )
            console.print(table)
    except Exception as exc:
        _fail(str(exc))


@config_app.command("show")
def config_show(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Print effective repository-local configuration."""
    try:
        with _arc(repo, project_id) as arc:
            console.print(yaml.safe_dump(arc.config.model_dump(mode="json", exclude_none=True), sort_keys=False))
    except Exception as exc:
        _fail(str(exc))


@config_app.command("default-agent")
def config_default_agent(
    name: str,
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Set the default named execution profile."""
    try:
        with _arc(repo, project_id) as arc:
            if name not in arc.config.agents:
                _fail(f"Agent profile {name!r} not found")
            arc.config.default_agent = name
            arc.config_store.save(arc.config)
            console.print(f"Default agent → [cyan]{name}[/cyan]")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@memory_app.command("list")
def memory_list(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """List active derived memories."""
    try:
        with _arc(repo, project_id) as arc:
            memories = arc.memory.get_active_memories(arc.project_id)
            table = Table(title=f"Adaptive memory // {len(memories)} active", box=box.SIMPLE_HEAVY)
            table.add_column("Memory", style="cyan")
            table.add_column("Type", style="yellow")
            table.add_column("Content", ratio=3)
            table.add_column("Created", justify="right")
            table.add_column("Confidence", justify="right")
            for memory in memories:
                table.add_row(
                    memory.memory_id,
                    memory.type.value,
                    memory.content_text[:100],
                    str(memory.created_event),
                    f"{memory.confidence:.2f}",
                )
            console.print(table)
    except Exception as exc:
        _fail(str(exc))


@memory_app.command("why")
def memory_why(
    memory_id: str,
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Explain a memory's provenance, validity, and supersession state."""
    try:
        with _arc(repo, project_id) as arc:
            memory = arc.memory.get_memory(memory_id)
            if not memory:
                _fail(f"Memory {memory_id} not found")
            body = (
                f"type: {memory.type.value}\nstatus: {memory.status.value}\n"
                f"source events: {memory.source_events}\n"
                f"valid: {memory.valid_from_event} → {memory.valid_to_event or 'current'}\n"
                f"superseded by: {memory.superseded_by or '-'}\n"
                f"access count: {memory.access_count}\n\n{memory.content_text}"
            )
            console.print(Panel(body, title=f"Memory provenance // {memory_id}", border_style="cyan"))
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(str(exc))


@memory_app.command("consolidate")
def memory_consolidate(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Consolidate redundant failure memory into reusable procedures."""
    try:
        with _arc(repo, project_id) as arc:
            current = arc.event_store.current_version(arc.project_id)
            count = arc.memory.consolidate(project_id=arc.project_id, upto_event=current)
            console.print(f"[green]Consolidation complete[/green] — generated procedures: {count}")
    except Exception as exc:
        _fail(str(exc))


@memory_app.command("rebuild-index")
def memory_rebuild_index(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Rebuild derived retrieval indexes from persistent memory rows."""
    try:
        with _arc(repo, project_id) as arc:
            arc.memory.rebuild_indexes_from_memories()
            console.print("[green]Derived memory indexes rebuilt[/green]")
    except Exception as exc:
        _fail(str(exc))


@context_app.command("build")
@context_app.command("inspect")
def context_build(
    task_id: str,
    agent: Optional[str] = typer.Option(None, help="Target named agent profile"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Compile and inspect an immutable ContextPacket for a task."""
    try:
        with _arc(repo, project_id) as arc:
            packet = arc.compile_context(task_id, agent_name=agent)
            body = (
                f"digest: {packet.digest}\nstate version: {packet.state_version}\n"
                f"tokens: {packet.context_token_count}\nmemories: {', '.join(packet.memory_ids) or '-'}\n"
                f"decisions: {len(packet.decisions)}  assumptions: {len(packet.assumptions)}\n"
                f"failures: {len(packet.failures)}  procedures: {len(packet.procedures)}\n"
                f"code evidence: {len(packet.code_context)}"
            )
            console.print(Panel(body, title=f"Context // {packet.context_id}", border_style="green"))
    except Exception as exc:
        _fail(str(exc))


@gate_app.command("inspect")
def gate_inspect(
    task_id: str,
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Show integration-gate events for a task."""
    try:
        with _arc(repo, project_id) as arc:
            events = [event for event in arc.task_events(task_id) if event.kind.startswith("gate.")]
            console.print(_events_table(events, title=f"Gate trail // {task_id}"))
    except Exception as exc:
        _fail(str(exc))


@app.command()
def dashboard(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: Optional[str] = typer.Option(None, help="Project identifier"),
) -> None:
    """Open the interactive ARC terminal Mission Control dashboard."""
    try:
        from tui.dashboard import run_dashboard

        run_dashboard(repo=repo, project_id=project_id)
    except Exception as exc:
        _fail(str(exc))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
