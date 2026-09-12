"""Cross-repository preregistration and hierarchical meta-analysis CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from eval.studies.meta import (
    aggregate_meta_study,
    create_meta_preregistration,
    load_meta_preregistration,
    load_study_plans,
    save_meta_preregistration,
)


console = Console()


def _metric_text(metric) -> str:
    if metric.mean_delta is None:
        return "-"
    return (
        f"{metric.mean_delta:+.4f} "
        f"[{metric.ci_lower:+.4f}, {metric.ci_upper:+.4f}] "
        f"repos={metric.repository_count}, reps={metric.repetition_count}"
    )


def register_meta_commands(benchmark_app: typer.Typer) -> None:
    @benchmark_app.command("meta-preregister")
    def preregister_meta_study(
        study_plans: list[Path] = typer.Argument(
            ...,
            help="Two or more preregistered per-repository study-plan JSON files.",
        ),
        meta_id: str = typer.Option(..., help="Stable cross-repository study identifier"),
        output: Path = typer.Option(
            Path("arc-meta-plan.json"),
            help="New self-digesting meta-study plan JSON",
        ),
        bootstrap_samples: int = typer.Option(
            5000,
            min=1,
            help="Hierarchical bootstrap resamples",
        ),
        ci: float = typer.Option(0.95, min=0.01, max=0.99),
        seed: int = typer.Option(42, help="Deterministic hierarchical-bootstrap seed"),
    ) -> None:
        """Freeze repository selection and cross-repository analysis before results."""
        try:
            if len(study_plans) < 2:
                raise typer.BadParameter(
                    "meta preregistration requires at least two repository study plans"
                )
            plans = load_study_plans(study_plans)
            meta = create_meta_preregistration(
                plans,
                meta_id=meta_id,
                bootstrap_samples=bootstrap_samples,
                ci=ci,
                random_seed=seed,
            )
            saved = save_meta_preregistration(output, meta)
            console.print(f"meta_preregistration={saved.resolve()}")
            console.print(f"meta_plan_digest={meta.plan_digest}")
            console.print(
                "repositories=" + ",".join(item.benchmark_id for item in meta.repositories)
            )
            console.print(
                "[dim]Repository selection is now frozen. Completed studies must carry "
                "the exact preregistered plan digests before meta-analysis.[/dim]"
            )
        except typer.BadParameter:
            raise
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc

    @benchmark_app.command("meta")
    def run_meta_study(
        meta_plan: Path = typer.Argument(..., help="Frozen ARC meta-study plan JSON"),
        study_dirs: list[Path] = typer.Argument(
            ...,
            help="Completed preregistered repeated-study artifact directories",
        ),
        output_dir: Optional[Path] = typer.Option(
            None,
            help="New output directory; defaults to <meta-id>-meta",
        ),
    ) -> None:
        """Aggregate completed repositories with repository-first hierarchical bootstrap."""
        try:
            if len(study_dirs) < 2:
                raise typer.BadParameter("meta-analysis requires at least two study directories")
            plan = load_meta_preregistration(meta_plan)
            target = output_dir or Path(f"{plan.meta_id}-meta")
            result = aggregate_meta_study(plan, study_dirs, output_dir=target)

            table = Table(title=f"Cross-repository meta-study // {result.meta_id}")
            table.add_column("Pair", style="cyan")
            table.add_column("Repo W/T/L", justify="right")
            table.add_column("Δ resolved rate")
            table.add_column("Δ context tokens")
            table.add_column("Δ cost")
            for comparison in result.comparisons:
                table.add_row(
                    f"{comparison.baseline_a}-{comparison.baseline_b}",
                    (
                        f"{comparison.repository_wins_a}/"
                        f"{comparison.repository_ties}/"
                        f"{comparison.repository_wins_b}"
                    ),
                    _metric_text(comparison.metrics["resolved_rate"]),
                    _metric_text(comparison.metrics["mean_context_tokens"]),
                    _metric_text(comparison.metrics["mean_cost_usd"]),
                )
            console.print(table)
            console.print(f"repositories={result.repository_count}")
            console.print(f"meta_plan_digest={result.plan_digest}")
            console.print(f"artifacts={result.artifact_dir}")
            console.print(
                "[dim]Inference unit: repository cluster. ARC resamples repositories "
                "first and paired repetitions inside each selected repository second.[/dim]"
            )
        except typer.BadParameter:
            raise
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc
