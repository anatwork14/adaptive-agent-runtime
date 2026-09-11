"""Command Line Interface for Adaptive Runtime Context (arc)."""

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from context.compiler import ContextCompiler
from context.request import ContextRequest
from context.retrieval import MemoryRetriever
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from runtime.replay import ReplayEngine
from state.events import EventStore
from state.projection import DeterministicStateProjection

app = typer.Typer(
    name="arc",
    help="Reliable Context Control for Long-Horizon Multi-Agent Coding",
    add_completion=False,
)
memory_app = typer.Typer(help="Inspect and manage the Adaptive Memory Plane.")
context_app = typer.Typer(help="Inspect and compile agent Context Packets.")
eval_app = typer.Typer(help="Run benchmarks and evaluation suites.")

app.add_typer(memory_app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(eval_app, name="eval")

console = Console()


def _get_paths(repo: Path = Path(".")):
    arc_dir = repo / ".arc"
    arc_dir.mkdir(parents=True, exist_ok=True)
    db_path = arc_dir / "state.db"
    return arc_dir, db_path


@app.command()
def init(
    repo: Path = typer.Argument(Path("."), help="Path to repository to initialize"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """Initialize an ARC runtime environment in the repository."""
    arc_dir, db_path = _get_paths(repo)
    store = EventStore(db_path)
    store.append(
        actor="cli",
        kind="project.created",
        project_id=project_id,
        payload={"spec": {"repo": str(repo.resolve())}, "constraints": []},
    )
    store.close()
    rprint(f"[bold green]Initialized ARC runtime in[/bold green] [cyan]{arc_dir}[/cyan] (Project: {project_id})")


@app.command()
def status(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """Display current authoritative project state, task DAG, and budget."""
    _, db_path = _get_paths(repo)
    if not db_path.exists():
        rprint("[red]No ARC environment found. Run 'arc init' first.[/red]")
        raise typer.Exit(1)

    store = EventStore(db_path)
    events = store.read_all(project_id=project_id)
    proj = DeterministicStateProjection.replay_from_events(project_id, events)

    console.rule(f"[bold blue]Project: {project_id} (State Version: {proj.version})[/bold blue]")

    # Project details
    rprint(f"[bold]Status:[/bold] {proj.project.state.status}")
    rprint(f"[bold]Constraints:[/bold] {proj.project.state.constraints or 'None'}")
    rprint(f"[bold]Budget Consumed:[/bold] ${proj.budgets.state.consumed_usd:.2f} / ${proj.budgets.state.hard_project_ceiling_usd:.2f} ({proj.budgets.state.consumed_tokens} tokens)")

    # Tasks Table
    table = Table(title="Task DAG", show_header=True, header_style="bold magenta")
    table.add_column("Task ID", style="cyan")
    table.add_column("Goal", style="white")
    table.add_column("Status", style="green")
    table.add_column("Dependencies", style="yellow")
    table.add_column("Risk", style="red")

    for tid, t in proj.dag.tasks.items():
        table.add_row(
            tid,
            t.goal[:40] + ("..." if len(t.goal) > 40 else ""),
            t.status.value,
            ", ".join(t.dependencies) or "-",
            f"{t.risk:.2f}",
        )
    console.print(table)
    store.close()


@app.command()
def events(
    after: int = typer.Option(0, help="Show events strictly after this ID"),
    limit: int = typer.Option(20, help="Maximum number of events to show"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """List authoritative events from the append-only log."""
    _, db_path = _get_paths(repo)
    store = EventStore(db_path)
    evs = store.read_after(after, project_id=project_id, limit=limit)

    table = Table(title=f"Authoritative Events (Project: {project_id})", show_header=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Actor", style="yellow")
    table.add_column("Kind", style="green")
    table.add_column("Task ID", style="magenta")
    table.add_column("Payload Summary", style="white")

    for ev in evs:
        p_str = json.dumps(ev.payload)
        summary = p_str[:50] + ("..." if len(p_str) > 50 else "")
        table.add_row(str(ev.id), ev.actor, ev.kind, ev.task_id or "-", summary)

    console.print(table)
    store.close()


@app.command()
def replay(
    upto: Optional[int] = typer.Option(None, help="Replay up to event ID"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """Replay authoritative event history to reconstruct projections from scratch."""
    _, db_path = _get_paths(repo)
    store = EventStore(db_path)
    engine = ReplayEngine(store)
    proj = engine.replay_project(project_id, upto_event_id=upto)
    rprint(f"[bold green]Replay successful![/bold green] Reconstructed project to version [bold cyan]{proj.version}[/bold cyan]")
    rprint(f"Tasks: {len(proj.dag.tasks)}, Completed: {len(proj.project.state.completed_tasks)}, Consumed USD: ${proj.budgets.state.consumed_usd:.2f}")
    store.close()


@memory_app.command("list")
def memory_list(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """List active memories in the Adaptive Memory Plane."""
    _, db_path = _get_paths(repo)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    memories = lifecycle.get_active_memories(project_id)
    table = Table(title=f"Active Adaptive Memories (Count: {len(memories)})", show_header=True)
    table.add_column("Memory ID", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Content Summary", style="white")
    table.add_column("Created Ev", style="magenta")
    table.add_column("Confidence", style="green")

    for m in memories:
        table.add_row(
            m.memory_id,
            m.type.value,
            m.content_text[:50] + ("..." if len(m.content_text) > 50 else ""),
            str(m.created_event),
            f"{m.confidence:.2f}",
        )
    console.print(table)
    conn.close()


@memory_app.command("why")
def memory_why(
    memory_id: str = typer.Argument(..., help="Memory identifier to inspect provenance for"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
):
    """Section 76: Inspect the exact provenance, validity interval, and downstream delivery of a memory."""
    _, db_path = _get_paths(repo)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)
    mem = lifecycle.get_memory(memory_id)

    if not mem:
        rprint(f"[red]Memory {memory_id} not found.[/red]")
        conn.close()
        raise typer.Exit(1)

    console.rule(f"[bold cyan]Memory Provenance: {memory_id}[/bold cyan]")
    rprint(f"[bold]Type:[/bold] {mem.type.value}")
    rprint(f"[bold]Status:[/bold] {mem.status.value}")
    rprint(f"[bold]Derived from Events:[/bold] {mem.source_events}")
    rprint(f"[bold]Valid Interval:[/bold] Event {mem.valid_from_event} -> {mem.valid_to_event or 'current'}")
    rprint(f"[bold]Content:[/bold]\n  {mem.content_text}")
    if mem.superseded_by:
        rprint(f"[bold red]Superseded by:[/bold red] {mem.superseded_by}")
    rprint(f"[bold]Access Count:[/bold] {mem.access_count}")
    conn.close()


@memory_app.command("consolidate")
def memory_consolidate(
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """Consolidate redundant failure memories into reusable procedures."""
    _, db_path = _get_paths(repo)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)
    store = EventStore(db_path)

    curr_v = store.current_version(project_id)
    consolidated = lifecycle.consolidate(project_id=project_id, upto_event=curr_v)
    rprint(f"[green]Consolidation complete.[/green] Generated procedures: {consolidated}")
    conn.close()
    store.close()


@memory_app.command("rebuild-index")
def memory_rebuild_index(repo: Path = typer.Option(Path("."), help="Repository root")):
    """Rebuild all derived FTS and vector indexes from persistent memory tables."""
    _, db_path = _get_paths(repo)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)
    lifecycle.rebuild_indexes_from_memories()
    rprint("[bold green]Derived indexes (FTS5 + Vector) rebuilt successfully![/bold green]")
    conn.close()


@context_app.command("build")
def context_build(
    task_id: str = typer.Argument(..., help="Task ID to build context for"),
    agent: str = typer.Option("codex", help="Target agent identifier"),
    repo: Path = typer.Option(Path("."), help="Repository root"),
    project_id: str = typer.Option("default", help="Project identifier"),
):
    """Compile and display an immutable ContextPacket for a task."""
    _, db_path = _get_paths(repo)
    store = EventStore(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    lifecycle = MemoryLifecycle(conn)

    events = store.read_all(project_id=project_id)
    proj = DeterministicStateProjection.replay_from_events(project_id, events)
    task = proj.dag.tasks.get(task_id)
    if not task:
        rprint(f"[red]Task {task_id} not found.[/red]")
        store.close()
        conn.close()
        raise typer.Exit(1)

    req = ContextRequest(
        context_request_id=f"CR_{task_id}",
        project_id=project_id,
        task_id=task_id,
        agent_id=agent,
        state_version=proj.version,
        goal=task.goal,
        risk=task.risk,
        files_declared=task.files_declared,
        symbols=task.symbols,
        dependencies=task.dependencies,
        token_budget=task.token_budget,
    )

    retriever = MemoryRetriever(lifecycle)
    compiler = ContextCompiler(store)
    retrieval_res = retriever.retrieve(req)
    packet = compiler.compile(req, retrieval_res, proj.project.state, task)

    console.rule(f"[bold green]Compiled Context Packet: {packet.context_id}[/bold green]")
    rprint(f"[bold]Digest:[/bold] {packet.digest}")
    rprint(f"[bold]Tokens:[/bold] {packet.context_token_count} / {task.token_budget}")
    rprint(f"[bold]Decisions Included:[/bold] {len(packet.decisions)}")
    rprint(f"[bold]Procedures Included:[/bold] {len(packet.procedures)}")
    rprint(f"[bold]Failures Included:[/bold] {len(packet.failures)}")
    rprint(f"[bold]Memory IDs:[/bold] {packet.memory_ids}")

    store.close()
    conn.close()


@context_app.command("diff")
def context_diff(
    context_a: str = typer.Argument(..., help="Context ID A"),
    context_b: str = typer.Argument(..., help="Context ID B"),
):
    """Diff two context packets by memory IDs and token counts."""
    rprint(f"Comparing context {context_a} and {context_b}...")


def main():
    app()


if __name__ == "__main__":
    main()
