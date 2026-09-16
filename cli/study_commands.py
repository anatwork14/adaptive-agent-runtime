"""Pre-registration, execution, and tidy export commands for ARC research studies."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from application.agents import build_agent, doctor_profile, profile_invocation_config
from application.config import ConfigStore
from eval.io import load_manifest
from eval.runners.repeated import AggregateMetric, RepeatedPairedBenchmarkRunner
from eval.studies.export import export_study_tidy
from eval.studies.preregistration import (
    create_preregistration,
    load_preregistration,
    save_preregistration,
    validate_execution_environment,
)

console = Console()
VALID_VERIFICATION_LEVELS = {"V0", "V1", "V2", "V3"}


def _load_v13_production_state():
    path = Path(__file__).parents[1] / "eval" / "campaigns" / "context-policy-multirepo-v13" / "production_state.py"
    spec = importlib.util.spec_from_file_location("context_policy_v13_production_state", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load V13 production state: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _print_result(result) -> None:
    table = Table(title=f"Preregistered study // {result.study_id}")
    table.add_column("Pair", style="cyan")
    table.add_column("W/T/L", justify="right")
    table.add_column("Δ resolved")
    table.add_column("Δ context")
    table.add_column("Δ cost")
    for aggregate in result.aggregates:
        table.add_row(
            f"{aggregate.baseline_a}-{aggregate.baseline_b}",
            f"{aggregate.wins_a}/{aggregate.ties}/{aggregate.wins_b}",
            _fmt_metric(aggregate.resolved_rate_delta),
            _fmt_metric(aggregate.mean_context_tokens_delta, digits=1),
            _fmt_metric(aggregate.mean_cost_usd_delta, digits=6),
        )
    console.print(table)
    console.print(f"artifacts={result.artifact_dir}")


def _load_configured_profile(manifests, repo: Path, project_id: Optional[str]):
    profiles = {manifest.agent_profile for manifest in manifests}
    models = {manifest.model for manifest in manifests}
    if len(profiles) != 1:
        raise typer.BadParameter("all manifests must declare one agent_profile")
    if len(models) != 1:
        raise typer.BadParameter("all manifests must declare one model")
    config = ConfigStore(repo).load(project_id)
    profile_name = next(iter(profiles))
    profile = config.agents.get(profile_name)
    if profile is None:
        raise typer.BadParameter(
            f"manifest agent_profile {profile_name!r} is not configured in ARC"
        )
    declared_model = next(iter(models))
    if declared_model != profile.model:
        raise typer.BadParameter(
            "manifest model does not match configured agent profile: "
            f"manifest={declared_model!r}, profile={profile.model!r}"
        )
    return config, profile


def _provider_codex_config_sha256(profile) -> str | None:
    """Return the live non-secret Codex config identity for contract validation."""
    if profile.provider != "codex" or not profile.codex_config_path:
        return None
    config_path = Path(profile.codex_config_path).expanduser().resolve()
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def register_study_commands(benchmark_app: typer.Typer) -> None:
    @benchmark_app.command("preregister")
    def preregister_benchmark(
        manifests: list[Path] = typer.Argument(
            ...,
            help="Matched B3/B5/B7 manifests to embed into the frozen study plan.",
        ),
        repo: Path = typer.Option(Path("."), help="Source Git repository under evaluation"),
        project_id: Optional[str] = typer.Option(
            None,
            help="ARC config project override used only to resolve the agent profile",
        ),
        study_id: str = typer.Option(..., help="Stable preregistered study identifier"),
        output: Path = typer.Option(
            Path("arc-study-plan.json"),
            help="New preregistration JSON file; existing files are never overwritten",
        ),
        repeats: int = typer.Option(6, min=2),
        bootstrap_samples: int = typer.Option(2000, min=1),
        ci: float = typer.Option(0.95, min=0.01, max=0.99),
        verification_level: str = typer.Option(
            "V0",
            "--verification-level",
            help="Frozen IntegrationGate verification level: V0, V1, V2, or V3.",
        ),
        hidden_test_dir: Optional[Path] = typer.Option(
            None,
            help="Optional external hidden-test tree to hash into the frozen contract",
        ),
        exclusion: list[str] = typer.Option(
            [],
            "--exclude",
            help="Predeclared exclusion rule; repeat to register multiple rules",
        ),
    ) -> None:
        """Freeze manifests, execution settings, analysis choices, and test digest."""
        try:
            if len(manifests) < 2:
                raise typer.BadParameter("preregistration requires at least two manifests")
            if verification_level not in VALID_VERIFICATION_LEVELS:
                allowed = ", ".join(sorted(VALID_VERIFICATION_LEVELS))
                raise typer.BadParameter(
                    f"verification_level must be one of {allowed}; got {verification_level!r}"
                )
            if output.exists():
                raise typer.BadParameter(
                    f"preregistration output already exists; choose a new path: {output}"
                )
            loaded = [load_manifest(path) for path in manifests]
            config, profile = _load_configured_profile(loaded, repo, project_id)
            plan = create_preregistration(
                loaded,
                repo,
                study_id=study_id,
                provider=profile.provider,
                profile_role=profile.role,
                profile_capabilities=profile.capabilities,
                visible_test_cmd=config.visible_test_cmd,
                visible_test_harness=config.visible_test_harness,
                hard_project_usd=config.hard_project_usd,
                hidden_test_dir=hidden_test_dir,
                verification_level=verification_level,
                repeats=repeats,
                bootstrap_samples=bootstrap_samples,
                ci=ci,
                exclusions=exclusion,
            )
            saved = save_preregistration(output, plan)
            console.print(f"preregistration={saved.resolve()}")
            console.print(f"plan_digest={plan.plan_digest}")
            console.print(f"repo_commit={plan.canonical_repo_commit}")
            console.print(f"verification_level={plan.runtime.verification_level}")
            console.print("comparisons=" + ",".join(plan.planned_comparisons))
            console.print(
                "[dim]Provider login is not required to preregister. `run-plan` "
                "revalidates the frozen contract and requires provider readiness.[/dim]"
            )
        except typer.BadParameter:
            raise
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc

    @benchmark_app.command("run-plan")
    def run_preregistered_plan(
        plan_file: Path = typer.Argument(..., help="Preregistered ARC study plan JSON"),
        repo: Path = typer.Option(Path("."), help="Source Git repository under evaluation"),
        project_id: Optional[str] = typer.Option(
            None,
            help="ARC config project override used only to resolve the agent profile",
        ),
        attempt_id: str = typer.Option(
            "a001",
            help="Explicit attempt identifier retained in provenance; change it for retries",
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
            help="External hidden-test tree; must match the preregistered digest",
        ),
        qualification_only: bool = typer.Option(
            False,
            "--qualification-only",
            help=(
                "Validate the frozen run-plan environment and stop before creating a runner "
                "or invoking a provider."
            ),
        ),
        production_ledger: Optional[Path] = typer.Option(
            None,
            "--production-ledger",
            help="Authoritative V13 SQLite ledger for the real production path",
        ),
        production_manifest: Optional[Path] = typer.Option(
            None,
            "--production-manifest",
            help="V13 pre-execution manifest paired with the authoritative ledger",
        ),
        production_checkpoint: Optional[Path] = typer.Option(
            None,
            "--production-checkpoint",
            help="V13 checkpoint export paired with the authoritative ledger",
        ),
        production_campaign_id: Optional[str] = typer.Option(
            None,
            "--production-campaign-id",
        ),
        production_attempt_id: Optional[str] = typer.Option(
            None,
            "--production-attempt-id",
        ),
        production_repository: Optional[str] = typer.Option(
            None,
            "--production-repository",
        ),
    ) -> None:
        """Execute exactly the frozen preregistered repeated-study contract."""
        try:
            if not attempt_id or any(ch.isspace() for ch in attempt_id):
                raise typer.BadParameter("attempt_id must be a non-empty token without whitespace")
            plan = load_preregistration(plan_file)
            config = ConfigStore(repo).load(project_id)
            profile = config.agents.get(plan.runtime.agent_profile)
            if profile is None:
                raise typer.BadParameter(
                    f"preregistered agent_profile {plan.runtime.agent_profile!r} "
                    "is not configured in ARC"
                )
            invocation_config = profile_invocation_config(
                profile,
                require_complete=(
                    profile.provider == "codex"
                    and plan.runtime.provider_codex_snapshot_path is not None
                ),
            )
            doctor = doctor_profile(profile)
            if doctor.status != "READY":
                raise typer.BadParameter(
                    f"agent profile {profile.name!r} is {doctor.status}: {doctor.detail}"
                )
            validate_execution_environment(
                plan,
                repo,
                provider=profile.provider,
                model=profile.model,
                profile_role=profile.role,
                profile_capabilities=profile.capabilities,
                visible_test_cmd=config.visible_test_cmd,
                visible_test_harness=config.visible_test_harness,
                hard_project_usd=config.hard_project_usd,
                hidden_test_dir=hidden_test_dir,
                verification_level=plan.runtime.verification_level,
                provider_execution_timeout_seconds=plan.runtime.provider_execution_timeout_seconds
                or config.provider_execution_timeout_seconds,
                provider_codex_home=profile.codex_home,
                provider_codex_config_path=profile.codex_config_path,
                provider_codex_config_sha256=_provider_codex_config_sha256(profile),
                provider_codex_snapshot_path=(
                    str(invocation_config.snapshot_path) if invocation_config else None
                ),
                provider_codex_snapshot_sha256=(
                    invocation_config.snapshot_sha256 if invocation_config else None
                ),
                provider_codex_snapshot_size=(
                    invocation_config.snapshot_size if invocation_config else None
                ),
                provider_codex_manifest_path=(
                    str(invocation_config.manifest_path)
                    if invocation_config and invocation_config.manifest_path
                    else None
                ),
                provider_codex_manifest_sha256=(
                    invocation_config.manifest_sha256 if invocation_config else None
                ),
                provider_codex_version=(
                    invocation_config.codex_version if invocation_config else None
                ),
                provider_codex_provider=(
                    invocation_config.provider if invocation_config else None
                ),
                provider_codex_authentication_required=(
                    invocation_config.authentication_required if invocation_config else None
                ),
                provider_codex_semantic_projection=(
                    dict(invocation_config.semantic_projection) if invocation_config else None
                ),
            )

            if qualification_only:
                console.print("run_plan_provider_environment_handoff=VERIFIED")
                console.print(f"provider_codex_home={profile.codex_home}")
                console.print(f"provider_codex_config_path={profile.codex_config_path}")
                console.print(
                    f"provider_codex_config_sha256={_provider_codex_config_sha256(profile)}"
                )
                console.print("provider_execution_started=false")
                return

            production_state = None
            production_ledger_handle = None
            if production_ledger is not None:
                required = {
                    "production-manifest": production_manifest,
                    "production-checkpoint": production_checkpoint,
                    "production-campaign-id": production_campaign_id,
                    "production-attempt-id": production_attempt_id,
                    "production-repository": production_repository,
                }
                missing = [name for name, value in required.items() if value in (None, "")]
                if missing:
                    raise typer.BadParameter(
                        "production integration options are incomplete: " + ", ".join(missing)
                    )
                production_state = _load_v13_production_state()
                production_ledger_handle = production_state.ProductionLedger(
                    production_ledger,
                    campaign_id=str(production_campaign_id),
                    attempt_id=str(production_attempt_id),
                    expected_tasks=162,
                    checkpoint_path=production_checkpoint,
                )
                if production_ledger_handle.logical_task_count() != 162:
                    raise typer.BadParameter("V13 production ledger must contain exactly 162 tasks")

            def task_observer_factory(repetition: int, manifest):
                if production_ledger_handle is None or production_state is None:
                    return None
                return production_state.ProductionTaskObserver(
                    production_ledger_handle,
                    repository=str(production_repository),
                    repetition=repetition,
                    baseline=manifest.baseline,
                    plan_digest=plan.plan_digest,
                    hidden_test_digest=manifest.runtime.hidden_tests_digest,
                    measurement_dir=production_ledger.parent / "measurements",
                    provider_model=str(manifest.model),
                    config_identity=_provider_codex_config_sha256(profile),
                    execution_mode=manifest.execution_mode,
                    timeout_seconds=int(manifest.runtime.provider_execution_timeout_seconds or 600),
                )

            runner = RepeatedPairedBenchmarkRunner(
                repo,
                output_root=output_root,
                workspace_root=workspace_root,
                verification_level=plan.runtime.verification_level,
                visible_test_cmd=config.visible_test_cmd or None,
                visible_test_harness=config.visible_test_harness or None,
                hard_project_usd=config.hard_project_usd,
                hidden_test_dir=hidden_test_dir,
                hidden_tests_required=plan.runtime.hidden_tests_required,
                provider_execution_timeout_seconds=plan.runtime.provider_execution_timeout_seconds
                or config.provider_execution_timeout_seconds,
                task_observer_factory=task_observer_factory if production_ledger is not None else None,
            )
            executed_study_id = f"{plan.study_id}-{attempt_id}"
            try:
                result = asyncio.run(
                    runner.run(
                    plan.manifests,
                    lambda: build_agent(profile),
                    repeats=plan.design.repeats,
                    study_id=executed_study_id,
                    n_bootstraps=plan.design.bootstrap_samples,
                    ci=plan.design.ci,
                    provenance_extra={
                        "provider": profile.provider,
                        "profile_role": profile.role,
                        "profile_capabilities": list(profile.capabilities),
                        "preregistered": True,
                        "preregistered_study_id": plan.study_id,
                        "attempt_id": attempt_id,
                        "plan_digest": plan.plan_digest,
                        "predeclared_exclusions": list(plan.design.exclusions),
                    },
                    )
                )
            finally:
                if production_ledger_handle is not None:
                    production_ledger_handle.close()
            _print_result(result)
            console.print(f"plan_digest={plan.plan_digest}")
            console.print(
                "[dim]Retries require a new explicit attempt ID and remain separate "
                "artifact trees; ARC never silently overwrites an earlier attempt.[/dim]"
            )
        except typer.BadParameter:
            raise
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc

    @benchmark_app.command("export")
    def export_benchmark_study(
        study_dir: Path = typer.Argument(
            ...,
            help="Completed repeated-study artifact directory",
        ),
        output_dir: Optional[Path] = typer.Option(
            None,
            help="Export destination; defaults to <study>/exports",
        ),
    ) -> None:
        """Export task-, repetition-, and pair-level tidy CSV/JSONL tables offline."""
        try:
            outputs = export_study_tidy(study_dir, output_dir)
            for name, path in outputs.items():
                console.print(f"{name}={path}")
        except Exception as exc:
            raise typer.BadParameter(str(exc)) from exc
