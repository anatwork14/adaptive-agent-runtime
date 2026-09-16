"""Exactly three focused V17 production-boundary regressions."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from typer.main import get_command

import cli.study_commands as study_commands
from adapters.mock import MockAgentAdapter
from cli.bootstrap import app
from eval.studies.preregistration import compute_plan_digest, save_preregistration
from eval.runners.experiment import ExperimentRunner

V17_CAMPAIGN_DIR = Path(__file__).parents[1] / "eval" / "campaigns" / "context-policy-multirepo-v17"
sys.path.insert(0, str(V17_CAMPAIGN_DIR))
import execute_campaign as v17_execute  # noqa: E402


V16_PLAN = Path("/Users/teobun/arc-secure/prereg/context-policy-multirepo-v16/click-context-policy-v16.json")
V16_PROFILE = Path("/Users/teobun/arc-study/runtime/context-policy-multirepo-v16/context-policy-multirepo-v16/postfreeze-boundary/profiles/click/config.yaml")
V16_HIDDEN = Path("/Users/teobun/arc-study/runtime-assets/context-policy-multirepo-v12/hidden/click")


def test_v17_run_plan_handoff_uses_sqlite_ledger_path(tmp_path: Path) -> None:
    ledger_path = tmp_path / "production-ledger.sqlite"
    manifest_path = tmp_path / "execution-manifest.json"
    command = v17_execute._build_production_run_plan_command(
        plan_path=tmp_path / "click-context-policy-v17.json",
        repo=tmp_path / "click",
        attempt_id="a001",
        output_root=tmp_path / "results",
        workspace_root=tmp_path / "workspace",
        hidden_dir=V16_HIDDEN,
        production_ledger_path=ledger_path,
        production_manifest_path=tmp_path / "pre-execution-manifest.json",
        production_checkpoint_path=tmp_path / "checkpoint.json",
        production_campaign_id="context-policy-multirepo-v17",
        production_repository="click",
        production_profile_path=tmp_path / "config.yaml",
    )

    ledger_argument = command[command.index("--production-ledger") + 1]
    assert ledger_argument == str(ledger_path)
    assert ledger_argument != str(manifest_path)
    with sqlite3.connect(ledger_path) as database:
        database.execute("CREATE TABLE probe (value INTEGER)")
        database.commit()


def test_v17_real_production_cli_reaches_pre_provider_stop_with_clean_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not V16_PLAN.is_file() or not V16_PROFILE.is_file():
        pytest.skip("requires the frozen V16 apparatus")

    from eval.studies.preregistration import PreregisteredStudy

    plan_payload = _replace_v16(json.loads(V16_PLAN.read_text(encoding="utf-8")))
    plan_payload["plan_digest"] = ""
    plan = PreregisteredStudy.model_validate(plan_payload)
    plan = plan.model_copy(update={"plan_digest": compute_plan_digest(plan)})
    plan_path = save_preregistration(tmp_path / "click-context-policy-v17.json", plan)

    profile_text = V16_PROFILE.read_text(encoding="utf-8").replace(
        "context-policy-multirepo-v16", "context-policy-multirepo-v17"
    ).replace("v16", "v17")
    profile_path = tmp_path / "config.yaml"
    profile_path.write_text(profile_text, encoding="utf-8")

    production_state = study_commands._load_production_state("v17")
    ledger_path = tmp_path / "production-ledger.sqlite"
    checkpoint_path = tmp_path / "checkpoint.json"
    ledger = production_state.ProductionLedger(
        ledger_path,
        campaign_id="context-policy-multirepo-v17",
        attempt_id="a001",
        expected_tasks=162,
        checkpoint_path=checkpoint_path,
    )
    ledger.register(production_state.build_campaign_identities())
    ledger.close()
    manifest_path = tmp_path / "pre-execution-manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    observed = {"observer": 0, "run_manifest": 0, "provider": 0}
    real_loader = study_commands._load_production_state

    def instrumented_loader(version: str):
        module = real_loader(version)
        base = module.ProductionTaskObserver

        class CountingObserver(base):
            def __init__(self, *args, **kwargs):
                observed["observer"] += 1
                super().__init__(*args, **kwargs)

        module.ProductionTaskObserver = CountingObserver
        return module

    monkeypatch.setattr(study_commands, "_load_production_state", instrumented_loader)
    monkeypatch.setattr(study_commands, "build_agent", lambda profile: MockAgentAdapter(profile.name))

    async def stop_before_provider(self, *args, **kwargs):
        observed["run_manifest"] += 1
        raise RuntimeError("V17_PRE_PROVIDER_STOP")

    monkeypatch.setattr(ExperimentRunner, "run_manifest", stop_before_provider)
    result = CliRunner().invoke(
        get_command(app),
        v17_execute._build_production_run_plan_command(
            plan_path=plan_path,
            repo=Path("/Users/teobun/arc-study/repos/click"),
            attempt_id="a001",
            output_root=tmp_path / "results",
            workspace_root=tmp_path / "workspace",
            hidden_dir=V16_HIDDEN,
            production_ledger_path=ledger_path,
            production_manifest_path=manifest_path,
            production_checkpoint_path=checkpoint_path,
            production_campaign_id="context-policy-multirepo-v17",
            production_repository="click",
            production_profile_path=profile_path,
        )[3:],
    )

    assert result.exit_code == 2
    assert "V17_PRE_PROVIDER_STOP" in result.output
    assert observed == {"observer": 1, "run_manifest": 1, "provider": 0}
    with sqlite3.connect(ledger_path) as database:
        assert database.execute("SELECT COUNT(*) FROM logical_tasks").fetchone()[0] == 162
        assert database.execute("SELECT COUNT(*) FROM execution_instances").fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM execution_instances WHERE provider_request_started=1").fetchone()[0] == 0


def test_v17_provider_started_metadata_tracks_authoritative_boundary(tmp_path: Path) -> None:
    production_state = study_commands._load_production_state("v17")
    ledger_path = tmp_path / "production-ledger.sqlite"
    ledger = production_state.ProductionLedger(
        ledger_path,
        campaign_id="context-policy-multirepo-v17",
        attempt_id="a001",
        expected_tasks=162,
    )
    identities = production_state.build_campaign_identities()
    ledger.register(identities)
    assert ledger.provider_execution_started() is False
    instance_id = ledger.start_execution(
        identities[0],
        request_id="req-v17-001",
        model="gpt-5.5",
        config_identity="frozen-v17",
    )
    assert ledger.provider_execution_started() is False
    ledger.mark_provider_started(instance_id, identity=identities[0])
    assert ledger.provider_execution_started() is True
    ledger.close()


def _replace_v16(value):
    if isinstance(value, str):
        return value.replace("context-policy-multirepo-v16", "context-policy-multirepo-v17").replace(
            "context-policy-click-v16", "context-policy-click-v17"
        ).replace("click-context-policy-v16", "click-context-policy-v17")
    if isinstance(value, list):
        return [_replace_v16(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_v16(item) for key, item in value.items()}
    return value
