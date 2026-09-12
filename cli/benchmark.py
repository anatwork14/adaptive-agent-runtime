"""Research benchmark commands for the installed ARC CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from application.agents import build_agent, doctor_profile
from application.config import ConfigStore
from eval.io import load_manifest
from eval.runners.paired import IsolatedPairedBenchmarkRunner

benchmark_app = typer.Typer(
    help="Run reproducible ARC research benchmarks.",
    no_args_is_help=True,
)
console = Console()


@benchmark_app.command("paired")
def paired_benchmark(
    manifests: list[Path] = typer.Argument(
        ...,
        help="Two or more matched B3/B5/B7 YAML/JSON manifests.",
    ),
    repo: Path = typer.Option(Path("."), help="Source Git repository under evaluation"),
    project_id: Optional[str] = typer.Option(
        None,
        help="ARC config project override used only to resolve the agent profile",
    ),
    output_root: Optional[Path] = typer.Option(
        None,
        help="Persistent benchmark artifacts; defaults outside the source repository",
    ),
    workspace_root: Optional[Path] = typer.Option(
        None,
        help="Disposable benchmark runtime root; defaults outside the source repository",
    ),
    hidden_test_dir: Optional[Path] = typer.Option(
        None,
        help="Optional external hidden-test directory",
    ),
    run_id: Optional[str] = typer.Option(None, help="Optional stable run identifier"),
) -> None:
    """Execute matched normalized baselines from independent reset environments."""
    try:
        if len(manifests) < 2:
            raise typer.BadParameter("paired benchmark requires at least two manifests")
        loaded = [load_manifest(path) for path in manifests]
        profiles = {manifest.agent_profile for manifest in loaded}
        if len(profiles) != 1:
            raise typer.BadParameter("all paired manifests must declare one agent_profile")
        profile_name = next(iter(profiles))

        config = ConfigStore(repo).load(project_id)
        profile = config.agents.get(profile_name)
        if profile is None:
            raise typer.BadParameter(
                f"manifest agent_profile {profile_name!r} is not configured in ARC"
            )

        declared_models = {manifest.model for manifest in loaded}
        if len(declared_models) != 1:
            raise typer.BadParameter("all paired manifests must declare the same model")
        declared_model = next(iter(declared_models))
        if declared_model != profile.model:
            raise typer.BadParameter(
                "manifest model does not match configured agent profile: "
                f"manifest={declared_model!r}, profile={profile.model!r}"
            )

        doctor = doctor_profile(profile)
        if doctor.status != "READY":
            raise typer.BadParameter(
                f"agent profile {profile.name!r} is {doctor.status}: {doctor.detail}"
            )

        runner = IsolatedPairedBenchmarkRunner(
            repo,
            output_root=output_root,
            workspace_root=workspace_root,
            visible_test_cmd=config.visible_test_cmd or None,
            hard_project_usd=config.hard_project_usd,
            hidden_test_dir=hidden_test_dir,
        )
        result = asyncio.run(
            runner.run(
                loaded,
                lambda: build_agent(profile),
                run_id=run_id,
            )
        )

        table = Table(title=f"Paired benchmark // {result.run_id}")
        table.add_column("Baseline", style="cyan")
        table.add_column("Resolved", justify="right")
        table.add_column("Mean context", justify="right")
        table.add_column("Final commit")
        for baseline, baseline_result in sorted(result.runs.items()):
            summary = baseline_result.summary
            mean_context = (
                f"{summary.mean_context_tokens:.1f}"
                if summary.mean_context_tokens is not None
                else "-"
            )
            table.add_row(
                baseline,
                f"{summary.resolved_count}/{summary.total_tasks}",
                mean_context,
                baseline_result.final_commit[:12],
            )
        console.print(table)
        console.print("execution_order=" + " -> ".join(result.execution_order))
        console.print(f"artifacts={result.artifact_dir}")
        console.print(
            "[dim]Mock-agent smoke runs validate the apparatus only; provider-backed "
            "runs are required for empirical model claims.[/dim]"
        )
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc
