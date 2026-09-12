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
from eval.runners.repeated import AggregateMetric, RepeatedPairedBenchmarkRunner

benchmark_app = typer.Typer(
    help="Run reproducible ARC research benchmarks.",
    no_args_is_help=True,
)
console = Console()


def _resolve_inputs(
    manifests: list[Path],
    repo: Path,
    project_id: Optional[str],
):
    if len(manifests) < 2:
        raise typer.BadParameter("benchmark requires at least two manifests")
    loaded = [load_manifest(path) for path in manifests]
    profiles = {manifest.agent_profile for manifest in loaded}
    if len(profiles) != 1:
        raise typer.BadParameter("all benchmark manifests must declare one agent_profile")
    profile_name = next(iter(profiles))

    config = ConfigStore(repo).load(project_id)
    profile = config.agents.get(profile_name)
    if profile is None:
        raise typer.BadParameter(
            f"manifest agent_profile {profile_name!r} is not configured in ARC"
        )

    declared_models = {manifest.model for manifest in loaded}
    if len(declared_models) != 1:
        raise typer.BadParameter("all benchmark manifests must declare the same model")
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
    return loaded, config, profile


def _fmt_metric(metric: AggregateMetric, digits: int = 4) -> str:
    if metric.mean_delta is None:
        return "-"
    lower = metric.ci_lower if metric.ci_lower is not None else metric.mean_delta
    upper = metric.ci_upper if metric.ci_upper is not None else metric.mean_delta
    return (
        f"{metric.mean_delta:+.{digits}f} "
        f"[{lower:+.{digits}f}, {upper:+.{digits}f}] "
        f"n={metric.sample_count}"
    )


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
        loaded, config, profile = _resolve_inputs(manifests, repo, project_id)
        runner = IsolatedPairedBenchmarkRunner(
            repo,
            output_root=output_root,
            workspace_root=workspace_root,
            visible_test_cmd=config.visible_test_cmd or None,
            visible_test_harness=config.visible_test_harness or None,
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


@benchmark_app.command("repeated")
def repeated_benchmark(
    manifests: list[Path] = typer.Argument(
        ...,
        help="Two or more matched B3/B5/B7 YAML/JSON manifests.",
    ),
    repo: Path = typer.Option(Path("."), help="Source Git repository under evaluation"),
    project_id: Optional[str] = typer.Option(
        None,
        help="ARC config project override used only to resolve the agent profile",
    ),
    repeats: int = typer.Option(
        6,
        min=2,
        help="Independent reset-safe paired repetitions; 6 covers both crossover orientations for 3 baselines.",
    ),
    bootstrap_samples: int = typer.Option(
        2000,
        min=1,
        help="Bootstrap resamples over repetition-level paired deltas.",
    ),
    ci: float = typer.Option(
        0.95,
        min=0.01,
        max=0.99,
        help="Bootstrap confidence-interval mass.",
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
    study_id: Optional[str] = typer.Option(None, help="Optional stable study identifier"),
) -> None:
    """Run repeated isolated paired trials with balanced treatment order and CIs."""
    try:
        loaded, config, profile = _resolve_inputs(manifests, repo, project_id)
        runner = RepeatedPairedBenchmarkRunner(
            repo,
            output_root=output_root,
            workspace_root=workspace_root,
            visible_test_cmd=config.visible_test_cmd or None,
            visible_test_harness=config.visible_test_harness or None,
            hard_project_usd=config.hard_project_usd,
            hidden_test_dir=hidden_test_dir,
        )
        result = asyncio.run(
            runner.run(
                loaded,
                lambda: build_agent(profile),
                repeats=repeats,
                study_id=study_id,
                n_bootstraps=bootstrap_samples,
                ci=ci,
                provenance_extra={
                    "provider": profile.provider,
                    "profile_role": profile.role,
                    "profile_capabilities": list(profile.capabilities),
                },
            )
        )

        table = Table(title=f"Repeated paired study // {result.study_id}")
        table.add_column("Pair", style="cyan")
        table.add_column("W/T/L", justify="right")
        table.add_column("Δ resolved")
        table.add_column("Δ context")
        table.add_column("Δ cost")
        table.add_column("Δ p95 latency")
        for aggregate in result.aggregates:
            table.add_row(
                f"{aggregate.baseline_a}-{aggregate.baseline_b}",
                f"{aggregate.wins_a}/{aggregate.ties}/{aggregate.wins_b}",
                _fmt_metric(aggregate.resolved_rate_delta),
                _fmt_metric(aggregate.mean_context_tokens_delta, digits=1),
                _fmt_metric(aggregate.mean_cost_usd_delta, digits=6),
                _fmt_metric(aggregate.p95_end_to_end_latency_ms_delta, digits=1),
            )
        console.print(table)
        console.print(
            "orders=" + " | ".join("->".join(item.execution_order) for item in result.repeats)
        )
        console.print("seeds=" + ",".join(str(seed) for seed in result.repeat_seeds))
        console.print(f"artifacts={result.artifact_dir}")
        console.print(
            "[dim]Inference unit: independent paired repetition. Positive deltas mean "
            "baseline A > baseline B. ARC seeds the treatment-order schedule; this is "
            "not a claim that an external provider's sampling is deterministic.[/dim]"
        )
    except typer.BadParameter:
        raise
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc
