"""Textual-based ARC terminal Mission Control dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from application.app import ArcApplication
from state.models import TaskStatus


class ArcDashboard(App[None]):
    """Interactive terminal mission control over the shared ARC application layer."""

    TITLE = "ARC Mission Control"
    SUB_TITLE = "Multi-Agent Orchestration"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "orchestrate", "Run fleet"),
        ("g", "run_selected", "Run task"),
        ("y", "retry_selected", "Retry"),
        ("x", "cancel_selected", "Cancel"),
    ]

    CSS = """
    Screen {
        background: #080b0a;
        color: #e7eadf;
    }
    Header, Footer {
        background: #111814;
        color: #dbe8df;
    }
    #top {
        height: 48%;
        min-height: 18;
    }
    #bottom {
        height: 1fr;
        min-height: 12;
    }
    #task-column {
        width: 2fr;
        border: solid #2b4035;
        background: #0c110f;
    }
    #side-column {
        width: 1fr;
        border: solid #2b4035;
        background: #0c110f;
    }
    #task-table {
        height: 1fr;
        background: #0a0f0d;
    }
    #agents, #system, #detail {
        padding: 1 2;
    }
    #agents {
        height: 1fr;
        border-bottom: solid #25372f;
    }
    #system {
        height: 1fr;
    }
    #detail {
        width: 2fr;
        border: solid #2b4035;
        background: #0c110f;
    }
    #events {
        width: 1fr;
        border: solid #2b4035;
        background: #070a09;
        padding: 0 1;
    }
    .section-title {
        height: 3;
        padding: 1 2;
        background: #111814;
        color: #f2b55f;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #253d32;
        color: #ffffff;
    }
    """

    def __init__(self, *, repo: str | Path = ".", project_id: Optional[str] = None) -> None:
        super().__init__()
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.arc: ArcApplication | None = None
        self.selected_task_id: str | None = None
        self.last_event_id = 0
        self._task_columns_added = False
        self._fleet_running = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top"):
            with Vertical(id="task-column"):
                yield Static("TASK DAG", classes="section-title")
                yield DataTable(id="task-table", zebra_stripes=True)
            with Vertical(id="side-column"):
                yield Static("AGENTS", classes="section-title")
                yield Static(id="agents")
                yield Static("SYSTEM", classes="section-title")
                yield Static(id="system")
        with Horizontal(id="bottom"):
            yield Static(id="detail")
            yield RichLog(id="events", highlight=True, markup=True, wrap=True, max_lines=250)
        yield Footer()

    def on_mount(self) -> None:
        self.arc = ArcApplication(self.repo, self.project_id)
        self.arc.require_initialized()
        table = self.query_one("#task-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Task", "Goal", "Status", "Agent", "Risk", "Try")
        self._task_columns_added = True
        existing = self.arc.recent_events(after=0, limit=30)
        for event in existing:
            self._write_event(event)
            self.last_event_id = max(self.last_event_id, event.id)
        self.refresh_dashboard()
        self.set_interval(0.75, self.refresh_dashboard, name="arc-dashboard-refresh")

    def on_unmount(self) -> None:
        if self.arc is not None:
            self.arc.close()
            self.arc = None

    @staticmethod
    def _status_markup(status: str) -> str:
        color = {
            "completed": "green",
            "failed": "red",
            "abandoned": "grey62",
            "ready": "cyan",
            "dispatched": "yellow",
            "submitted": "yellow",
            "blocked": "red",
            "created": "blue",
        }.get(status, "white")
        return f"[{color}]{status}[/{color}]"

    def refresh_dashboard(self) -> None:
        if self.arc is None:
            return
        try:
            snap = self.arc.snapshot()
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=3)
            return

        table = self.query_one("#task-table", DataTable)
        table.clear(columns=False)
        tasks = snap["tasks"]
        for task in tasks:
            table.add_row(
                task.task_id,
                task.goal[:52] + ("…" if len(task.goal) > 52 else ""),
                Text.from_markup(self._status_markup(task.status.value)),
                task.assigned_agent or "-",
                f"{task.risk:.2f}",
                str(task.attempt_count),
                key=task.task_id,
            )

        if self.selected_task_id is None and tasks:
            self.selected_task_id = tasks[0].task_id
        elif self.selected_task_id and not any(t.task_id == self.selected_task_id for t in tasks):
            self.selected_task_id = tasks[0].task_id if tasks else None

        self._refresh_agents()
        self._refresh_system(snap)
        self._refresh_detail()
        self._refresh_events()

    def _refresh_agents(self) -> None:
        assert self.arc is not None
        lines = []
        doctor_by_name = {row.name: row for row in self.arc.doctor_agents()}
        for profile in self.arc.list_agents():
            row = doctor_by_name[profile.name]
            marker = "●" if profile.name == self.arc.config.default_agent else "○"
            color = "green" if row.status == "READY" else "yellow" if row.status in {"GATEWAY_ONLY", "AUTH_REQUIRED"} else "red"
            caps = ",".join(profile.capabilities[:4]) or "-"
            lines.append(
                f"{marker} [bold cyan]{profile.name}[/bold cyan]  {profile.provider}"
                f"\n   [{color}]{row.status}[/{color}]  role={profile.role}  max={profile.max_concurrency}"
                f"\n   caps={caps}"
            )
        self.query_one("#agents", Static).update("\n\n".join(lines) or "No agents configured")

    def _refresh_system(self, snap: dict) -> None:
        assert self.arc is not None
        budget = snap["budget"]
        memories = self.arc.memory.get_active_memories(self.arc.project_id)
        ready = sum(1 for task in snap["tasks"] if task.status == TaskStatus.READY)
        active = sum(
            1
            for task in snap["tasks"]
            if task.status in {TaskStatus.DISPATCHED, TaskStatus.SUBMITTED}
        )
        orchestration = snap.get("orchestration", {})
        text = (
            f"[bold]Project[/bold]   {snap['project_id']}\n"
            f"[bold]State[/bold]     v{snap['version']}\n"
            f"[bold]Tasks[/bold]     {len(snap['tasks'])}  ready={ready} active={active}\n"
            f"[bold]Fleet[/bold]     policy={orchestration.get('routing_policy', '-')} max={orchestration.get('max_parallel', '-')}"
            f"{'  [yellow]RUNNING[/yellow]' if self._fleet_running else ''}\n"
            f"[bold]Memory[/bold]    {len(memories)} active\n"
            f"[bold]Budget[/bold]    ${budget.consumed_usd:.2f} / ${budget.hard_project_ceiling_usd:.2f}\n"
            f"[bold]Tokens[/bold]    {budget.consumed_tokens:,}\n"
            f"[bold]Leases[/bold]    {len(snap['leases'])} active"
        )
        self.query_one("#system", Static).update(text)

    def _refresh_detail(self) -> None:
        assert self.arc is not None
        detail = self.query_one("#detail", Static)
        if not self.selected_task_id:
            detail.update("[dim]Select a task to inspect it.[/dim]")
            return
        task = self.arc.get_task(self.selected_task_id)
        if task is None:
            detail.update("[red]Selected task disappeared from projection.[/red]")
            return
        recent = self.arc.task_events(task.task_id, limit=7)
        event_lines = "\n".join(f"  [dim]#{event.id}[/dim] {event.kind}" for event in recent) or "  -"
        route_text = ""
        if task.status == TaskStatus.READY:
            try:
                route = self.arc.route_task(task.task_id)
                route_text = f"route={route.agent_name} score={route.score:.2f} policy={route.policy}\n"
            except Exception as exc:
                route_text = f"route=[yellow]deferred[/yellow] ({exc})\n"
        text = (
            f"[bold cyan]{task.task_id}[/bold cyan]  {self._status_markup(task.status.value)}\n"
            f"[bold]{task.goal}[/bold]\n\n"
            f"type={task.task_type}  capabilities={','.join(task.required_capabilities) or '-'}\n"
            f"{route_text}"
            f"agent={task.assigned_agent or '-'}  attempt={task.attempt_count}  risk={task.risk:.2f}\n"
            f"dependencies={', '.join(task.dependencies) or '-'}\n"
            f"files={', '.join(task.files_declared) or '-'}\n"
            f"token ceiling={task.token_budget:,}\n"
            f"acceptance={'; '.join(task.acceptance_criteria) or '-'}\n\n"
            f"[bold]Recent authoritative events[/bold]\n{event_lines}\n\n"
            f"[dim]a run fleet • g run selected • y retry • x cancel • r refresh[/dim]"
        )
        detail.update(text)

    def _refresh_events(self) -> None:
        assert self.arc is not None
        events = self.arc.events.poll(self.last_event_id, limit=100)
        for event in events:
            self._write_event(event)
            self.last_event_id = event.id

    def _write_event(self, event) -> None:
        log = self.query_one("#events", RichLog)
        color = (
            "green"
            if event.kind in {"gate.accepted", "task.merged", "orchestration.task_finished"}
            else "red"
            if event.kind in {"task.failed", "gate.rejected", "task.abandoned", "orchestration.task_failed"}
            else "yellow"
            if event.kind.startswith("gate.") or event.kind == "orchestration.deferred"
            else "magenta"
            if event.kind.startswith("orchestration.")
            else "cyan"
        )
        log.write(
            f"[dim]#{event.id:04d}[/dim] [{color}]{event.kind}[/{color}] "
            f"[magenta]{event.task_id or '-'}[/magenta] [dim]{event.actor}[/dim]"
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.get_row_at(event.cursor_row)
        if row:
            self.selected_task_id = str(row[0])
            self._refresh_detail()

    def action_refresh(self) -> None:
        self.refresh_dashboard()
        self.notify("ARC state refreshed", timeout=1)

    async def action_orchestrate(self) -> None:
        if self.arc is None or self._fleet_running:
            return
        self._fleet_running = True
        self.refresh_dashboard()
        try:
            self.notify("ARC fleet routing READY tasks…", timeout=2)
            result = await self.arc.orchestrate()
            severity = "information" if result.successful else "warning"
            self.notify(
                f"{result.run_id}: accepted={len(result.accepted)} failed={len(result.failed) + len(result.rejected)}",
                severity=severity,
                timeout=4,
            )
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=5)
        finally:
            self._fleet_running = False
            self.refresh_dashboard()

    async def action_run_selected(self) -> None:
        if self.arc is None or not self.selected_task_id:
            return
        task = self.arc.get_task(self.selected_task_id)
        if task is None:
            return
        if task.status != TaskStatus.READY:
            self.notify(f"{task.task_id} is {task.status.value}, not READY", severity="warning")
            return
        try:
            route = self.arc.route_task(task.task_id)
            self.notify(f"Running {task.task_id} with {route.agent_name}", timeout=2)
            result = await self.arc.run_task(task.task_id, agent_name=route.agent_name)
            self.notify(f"Gate result: {result.status.value}", timeout=3)
            self.refresh_dashboard()
        except Exception as exc:
            self.notify(str(exc), severity="error", timeout=5)

    def action_retry_selected(self) -> None:
        if self.arc is None or not self.selected_task_id:
            return
        try:
            task = self.arc.retry_task(self.selected_task_id, reason="TUI operator retry")
            self.notify(f"{task.task_id} → {task.status.value}", timeout=2)
            self.refresh_dashboard()
        except Exception as exc:
            self.notify(str(exc), severity="warning", timeout=3)

    def action_cancel_selected(self) -> None:
        if self.arc is None or not self.selected_task_id:
            return
        try:
            task = self.arc.cancel_task(self.selected_task_id, reason="TUI operator cancelled")
            self.notify(f"{task.task_id} → {task.status.value}", timeout=2)
            self.refresh_dashboard()
        except Exception as exc:
            self.notify(str(exc), severity="warning", timeout=3)


def run_dashboard(*, repo: str | Path = ".", project_id: Optional[str] = None) -> None:
    ArcDashboard(repo=repo, project_id=project_id).run()
