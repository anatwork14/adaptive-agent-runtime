"""Interactive ARC shell — the default `arc` experience.

The shell intentionally feels closer to a coding-agent CLI than to an admin
command collection. Natural-language input plans work at project scope or sends
another instruction to the focused persistent worker session. Slash commands
expose precise operator and review-loop controls without leaving the conversation.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Optional

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from application.session_app import SessionArcApplication
from application.sessions import SessionStatus, WorkerSession

HELP = """[bold cyan]ARC commands[/bold cyan]
[cyan]/help[/cyan]                         show this help
[cyan]/status[/cyan]                       project + fleet summary
[cyan]/tasks[/cyan]                        authoritative task DAG
[cyan]/sessions[/cyan]                     worker sessions
[cyan]/open TASK [AGENT][/cyan]            open persistent worker on a READY task
[cyan]/focus SESSION|TASK[/cyan]            focus an existing worker
[cyan]/send SESSION TEXT[/cyan]             send instruction to a worker
[cyan]/files [SESSION][/cyan]               changed files in worker worktree
[cyan]/diff [SESSION][/cyan]                current worker diff
[cyan]/publish [SESSION][/cyan]             push worker branch and create/update PR
[cyan]/review [SESSION][/cyan]              synchronize GitHub checks/review feedback
[cyan]/fix-review [SESSION][/cyan]          route pending GitHub feedback to worker
[cyan]/submit [SESSION][/cyan]              freeze exact candidate and run ARC gate
[cyan]/stop [SESSION][/cyan]                stop worker and return task to READY
[cyan]/run[/cyan]                           route + run the READY fleet
[cyan]/attach [SESSION][/cyan]              show native terminal attach command
[cyan]/exit[/cyan]                          leave ARC

Without a focused worker, normal text is treated as a project objective and
planned into a task DAG. With a focused worker, normal text becomes the next
instruction for that worker. GitHub is an external review surface; ARC events,
tasks, Git candidates and gate outcomes remain authoritative.
"""


class ArcShell(App[None]):
    """Conversation-first local supervisor for ARC."""

    CSS = """
    Screen { background: #080c12; color: #d7e1ea; }
    #topbar { height: 3; padding: 0 2; background: #0d141e; border-bottom: solid #1f6f78; }
    #topbar Static { width: 1fr; content-align: left middle; }
    #workspace { height: 1fr; }
    #sidebar { width: 34; min-width: 28; padding: 1; background: #0a1018; border-right: solid #20313d; }
    #sessionList { height: 1fr; }
    #main { width: 1fr; }
    #conversation { height: 1fr; padding: 1 2; scrollbar-color: #287f8c; }
    #prompt { dock: bottom; margin: 0 1 1 1; border: tall #287f8c; background: #0e1621; }
    .muted { color: #718493; }
    Footer { background: #0a1018; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+s", "show_sessions", "Sessions"),
    ]

    def __init__(self, repo: Path, project_id: Optional[str] = None) -> None:
        super().__init__()
        self.repo = repo.resolve()
        self.project_id = project_id
        self.arc: SessionArcApplication | None = None
        self.focused_session_id: str | None = None
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("[bold cyan]ARC[/bold cyan]  Adaptive Agent Runtime", id="brand"),
            Static("starting…", id="projectState"),
            id="topbar",
        )
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Static("[bold]WORKERS[/bold]\n\nNo sessions yet.", id="sessionList")
            with Vertical(id="main"):
                yield RichLog(id="conversation", markup=True, wrap=True, highlight=True)
                yield Input(
                    placeholder="Ask ARC to build something, or type /help",
                    id="prompt",
                )
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.arc = SessionArcApplication(self.repo, self.project_id)
            self.arc.require_initialized()
        except Exception as exc:
            self.query_one("#conversation", RichLog).write(
                f"[bold red]ARC cannot start:[/bold red] {escape(str(exc))}\n"
                "Run [cyan]arc init[/cyan] in this repository first."
            )
            self.query_one("#prompt", Input).disabled = True
            return
        self._write_welcome()
        self._refresh_chrome()
        self.set_interval(1.5, self._refresh_chrome)
        self.query_one("#prompt", Input).focus()

    def on_unmount(self) -> None:
        if self.arc is not None:
            self.arc.close()

    def _write_welcome(self) -> None:
        assert self.arc is not None
        doctors = self.arc.doctor_agents()
        ready = [item.name for item in doctors if item.status == "READY"]
        connected = ", ".join(ready) if ready else "no real providers ready"
        review = self.arc.reviews.doctor()
        review_state = review.get("status", "UNKNOWN")
        log = self.query_one("#conversation", RichLog)
        log.write(
            "[bold cyan]ARC[/bold cyan] — persistent multi-agent coding supervisor\n"
            f"[dim]{self.repo}[/dim]\n\n"
            f"Providers: [green]{escape(connected)}[/green]\n"
            f"GitHub review loop: [cyan]{escape(review_state)}[/cyan]\n"
            "Describe an outcome to plan it, or [cyan]/open T001[/cyan] to work with one agent.\n"
            "Type [cyan]/help[/cyan] for controls."
        )

    def _refresh_chrome(self) -> None:
        if self.arc is None:
            return
        try:
            snap = self.arc.snapshot()
            sessions = self.arc.sessions.list()
            active = [session for session in sessions if session.status in self.arc.sessions.ACTIVE]
            self.query_one("#projectState", Static).update(
                f"[dim]{escape(self.arc.project_id)}[/dim]  "
                f"state [bold]v{snap['version']}[/bold]  "
                f"workers [cyan]{len(active)}[/cyan]"
            )
            lines = ["[bold]WORKERS[/bold]"]
            if not sessions:
                lines += ["", "[dim]No sessions yet.[/dim]"]
            for session in sessions[:12]:
                focused = "▶" if session.session_id == self.focused_session_id else " "
                status_color = {
                    SessionStatus.OPEN: "cyan",
                    SessionStatus.RUNNING: "yellow",
                    SessionStatus.NEEDS_INPUT: "magenta",
                    SessionStatus.ACCEPTED: "green",
                    SessionStatus.REJECTED: "red",
                    SessionStatus.FAILED: "red",
                    SessionStatus.STOPPED: "dim",
                    SessionStatus.SUBMITTED: "yellow",
                }.get(session.status, "white")
                review = self.arc.reviews.status(session.session_id)
                review_marker = ""
                if review.linked:
                    if review.pending_feedback or review.failed_checks:
                        review_marker = f" [red]PR#{review.pr_number}![/red]"
                    elif review.pending_checks:
                        review_marker = f" [yellow]PR#{review.pr_number}…[/yellow]"
                    else:
                        review_marker = f" [green]PR#{review.pr_number}[/green]"
                lines.append(
                    f"\n{focused} [bold]{session.task_id}[/bold]  "
                    f"[{status_color}]{session.status.value}[/]{review_marker}\n"
                    f"  [dim]{session.session_id} · {escape(session.agent_name)}[/dim]"
                )
            self.query_one("#sessionList", Static).update("\n".join(lines))
        except Exception:
            # Chrome refresh should never terminate an active conversation.
            return

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        event.input.value = ""
        if not raw or self.busy or self.arc is None:
            return
        self.busy = True
        event.input.disabled = True
        try:
            await self._process(raw)
        except Exception as exc:
            self.query_one("#conversation", RichLog).write(
                f"[bold red]ARC error:[/bold red] {escape(str(exc))}"
            )
        finally:
            self.busy = False
            event.input.disabled = False
            event.input.focus()
            self._refresh_chrome()

    async def _process(self, raw: str) -> None:
        log = self.query_one("#conversation", RichLog)
        log.write(f"\n[bold white]>[/bold white] {escape(raw)}")
        if raw.startswith("/"):
            await self._command(raw)
            return
        if self.focused_session_id:
            await self._send(self.focused_session_id, raw)
            return
        await self._plan_objective(raw)

    async def _command(self, raw: str) -> None:
        assert self.arc is not None
        log = self.query_one("#conversation", RichLog)
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            log.write(f"[red]{escape(str(exc))}[/red]")
            return
        command = parts[0].lower()
        args = parts[1:]

        if command in {"/exit", "/quit"}:
            self.exit()
        elif command == "/help":
            log.write(HELP)
        elif command == "/status":
            snap = self.arc.snapshot()
            tasks = snap["tasks"]
            active = len([s for s in self.arc.sessions.list() if s.status in self.arc.sessions.ACTIVE])
            linked = len([r for r in self.arc.reviews.list() if r.linked])
            attention = len(
                [r for r in self.arc.reviews.list() if r.pending_feedback or r.failed_checks]
            )
            log.write(
                f"[bold]STATE v{snap['version']}[/bold]  tasks={len(tasks)}  "
                f"workers={active}  reviews={linked}/{attention} attention  "
                f"leases={len(snap['leases'])}  tokens={snap['budget'].consumed_tokens:,}  "
                f"cost=${snap['budget'].consumed_usd:.2f}"
            )
        elif command == "/tasks":
            tasks = self.arc.list_tasks()
            if not tasks:
                log.write("[dim]No tasks.[/dim]")
            for task in tasks:
                log.write(
                    f"[cyan]{task.task_id}[/cyan]  {task.status.value:<10}  "
                    f"{escape(task.assigned_agent or '-'):<12}  {escape(task.goal)}"
                )
        elif command == "/sessions":
            sessions = self.arc.sessions.list()
            if not sessions:
                log.write("[dim]No worker sessions.[/dim]")
            for session in sessions:
                review = self.arc.reviews.status(session.session_id)
                pr = f"PR#{review.pr_number}" if review.linked else "-"
                log.write(
                    f"[cyan]{session.session_id}[/cyan]  {session.task_id}  "
                    f"{session.status.value:<11}  {escape(session.agent_name)}  {escape(pr)}"
                )
        elif command == "/open":
            if not args:
                log.write("[red]Usage: /open TASK [AGENT][/red]")
                return
            session = self.arc.sessions.create(args[0], agent_name=args[1] if len(args) > 1 else None)
            self.focused_session_id = session.session_id
            log.write(
                f"[green]Worker opened[/green]  [cyan]{session.session_id}[/cyan] → "
                f"{session.task_id} / {escape(session.agent_name)}\n"
                f"[dim]{escape(session.worktree_path)}[/dim]"
            )
        elif command == "/focus":
            if not args:
                log.write("[red]Usage: /focus SESSION|TASK[/red]")
                return
            session = self._resolve_session(args[0])
            self.focused_session_id = session.session_id
            log.write(f"Focused [cyan]{session.session_id}[/cyan] ({session.task_id})")
        elif command == "/send":
            if len(args) < 2:
                log.write("[red]Usage: /send SESSION TEXT[/red]")
                return
            session = self._resolve_session(args[0])
            await self._send(session.session_id, " ".join(args[1:]))
        elif command == "/files":
            session = self._focused_or(args[0] if args else None)
            files = self.arc.sessions.changed_files(session.session_id)
            log.write(
                "[bold]Changed files[/bold]\n"
                + ("\n".join(f"  {escape(file)}" for file in files) or "  none")
            )
        elif command == "/diff":
            session = self._focused_or(args[0] if args else None)
            diff = self.arc.sessions.diff(session.session_id)
            log.write(
                f"[bold]Diff // {session.session_id}[/bold]\n"
                f"{escape(diff or 'No uncommitted changes. Published commits remain on the worker branch.')}"
            )
        elif command == "/publish":
            session = self._focused_or(args[0] if args else None)
            doctor = self.arc.reviews.doctor()
            if doctor.get("status") != "READY":
                raise RuntimeError(
                    f"GitHub review loop is {doctor.get('status')}: {doctor.get('detail')}"
                )
            log.write(f"[yellow]Publishing {session.session_id} for GitHub review…[/yellow]")
            review = self.arc.reviews.publish(session.session_id)
            log.write(
                f"[green]PR #{review.pr_number}[/green]  {escape(review.pr_url)}\n"
                "[dim]Use /review to synchronize CI/reviewer feedback.[/dim]"
            )
        elif command == "/review":
            session = self._focused_or(args[0] if args else None)
            result = await self.arc.reviews.sync(session.session_id, auto_apply=False)
            review = result.status
            color = "green" if review.healthy else "yellow"
            log.write(
                f"[{color}]PR #{review.pr_number}[/]  state={escape(review.state or '-')}  "
                f"review={escape(review.review_decision or '-')}  "
                f"failed={len(review.failed_checks)}  pending={len(review.pending_checks)}"
            )
            if review.pending_feedback:
                log.write(
                    "[bold magenta]Actionable feedback pending[/bold magenta]\n"
                    + escape(review.pending_feedback)
                    + "\n[dim]Use /fix-review to route it to this worker.[/dim]"
                )
        elif command == "/fix-review":
            session = self._focused_or(args[0] if args else None)
            applied = await self.arc.reviews.apply_latest(session.session_id)
            if applied:
                log.write("[green]GitHub feedback routed to the same worker and a new turn completed.[/green]")
                self.focused_session_id = session.session_id
            else:
                log.write("[dim]No new actionable GitHub feedback to apply.[/dim]")
        elif command == "/submit":
            session = self._focused_or(args[0] if args else None)
            log.write(f"[yellow]Submitting {session.session_id} through ARC gate…[/yellow]")
            result = await self.arc.sessions.submit(session.session_id)
            color = "green" if result.status.value == "accepted" else "red"
            log.write(
                f"[{color}]{result.status.value.upper()}[/]  gate={escape(result.gate_run_id)}  "
                f"merged={escape(result.merged_commit_sha or '-')}"
            )
            if self.focused_session_id == session.session_id:
                self.focused_session_id = None
        elif command == "/stop":
            session = self._focused_or(args[0] if args else None)
            self.arc.sessions.stop(session.session_id)
            log.write(
                f"[yellow]Stopped {session.session_id}; {session.task_id} returned to scheduler.[/yellow]"
            )
            if self.focused_session_id == session.session_id:
                self.focused_session_id = None
        elif command == "/run":
            log.write("[yellow]Routing and running READY fleet…[/yellow]")
            result = await self.arc.orchestrate()
            log.write(
                f"Fleet finished: [green]{len(result.accepted)} accepted[/green], "
                f"[red]{len(result.failed) + len(result.rejected)} failed/rejected[/red], "
                f"{len(set(result.deferred))} deferred."
            )
        elif command == "/attach":
            session = self._focused_or(args[0] if args else None)
            cmd = " ".join(self.arc.sessions.native_command(session.session_id))
            log.write(
                "Native terminal attachment deliberately suspends the shell. Run:\n"
                f"[bold cyan]arc attach {session.session_id}[/bold cyan]\n"
                f"[dim]provider command: {escape(cmd)}[/dim]"
            )
        else:
            log.write(f"[red]Unknown command {escape(command)}[/red]. Type /help.")

    async def _plan_objective(self, objective: str) -> None:
        assert self.arc is not None
        log = self.query_one("#conversation", RichLog)
        self.arc.event_store.append(
            actor="operator",
            kind="shell.user_message",
            project_id=self.arc.project_id,
            correlation_id="project-orchestrator",
            payload={"content": objective},
        )
        plan, tasks = self.arc.plan_objective(objective)
        lines = [
            f"ARC planned [bold]{len(tasks)} task{'s' if len(tasks) != 1 else ''}[/bold] "
            f"using [cyan]{escape(plan.planner)}[/cyan]:"
        ]
        for task in tasks:
            try:
                route = self.arc.route_task(task.task_id)
                agent = route.agent_name
            except Exception:
                agent = "unrouted"
            lines.append(
                f"  [cyan]{task.task_id}[/cyan]  {escape(task.goal)}  [dim]→ {escape(agent)}[/dim]"
            )
        lines.append(
            "\nType [cyan]/run[/cyan] to execute the READY fleet, or "
            "[cyan]/open Txxx[/cyan] to supervise one worker interactively."
        )
        response = "\n".join(lines)
        log.write(response)
        self.arc.event_store.append(
            actor="orchestrator",
            kind="shell.assistant_message",
            project_id=self.arc.project_id,
            correlation_id="project-orchestrator",
            payload={"content": response, "task_ids": [task.task_id for task in tasks]},
        )

    async def _send(self, session_id: str, instruction: str) -> None:
        assert self.arc is not None
        log = self.query_one("#conversation", RichLog)
        session = self.arc.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        log.write(
            f"[yellow]{escape(session.agent_name)} is working in {session.task_id}…[/yellow]"
        )
        updated = await self.arc.sessions.send(session_id, instruction)
        self.focused_session_id = session_id
        if updated.messages:
            assistant = next(
                (msg for msg in reversed(updated.messages) if msg.role == "assistant"),
                None,
            )
            if assistant:
                log.write(
                    f"[bold cyan]{escape(updated.agent_name)}[/bold cyan]\n"
                    f"{escape(assistant.content)}"
                )
        files = self.arc.sessions.changed_files(session_id)
        if files:
            log.write("[dim]changed: " + escape(", ".join(files[:8])) + "[/dim]")

    def _resolve_session(self, raw: str) -> WorkerSession:
        assert self.arc is not None
        direct = self.arc.sessions.get(raw)
        if direct:
            return direct
        by_task = self.arc.sessions.for_task(raw)
        if by_task:
            return by_task
        raise ValueError(f"No worker session for {raw}")

    def _focused_or(self, raw: str | None) -> WorkerSession:
        if raw:
            return self._resolve_session(raw)
        if not self.focused_session_id:
            raise ValueError("No worker focused. Use /focus SESSION or /open TASK.")
        return self._resolve_session(self.focused_session_id)

    def action_clear_log(self) -> None:
        self.query_one("#conversation", RichLog).clear()

    def action_show_sessions(self) -> None:
        self.query_one("#prompt", Input).value = "/sessions"
        self.query_one("#prompt", Input).focus()


def run_shell(repo: str | Path = ".", project_id: Optional[str] = None) -> None:
    ArcShell(Path(repo), project_id).run()
