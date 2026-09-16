"""Focused V16 regressions for the production run-plan integration boundary."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from typer.main import get_command

import cli.study_commands as study_commands
from adapters.mock import MockAgentAdapter
from cli.bootstrap import app
from eval.studies.preregistration import compute_plan_digest, save_preregistration


V15_PLAN = Path("/Users/teobun/arc-secure/prereg/context-policy-multirepo-v15/click-context-policy-v15.json")
V15_PROFILE = Path(
    "/Users/teobun/arc-study/runtime/context-policy-multirepo-v15/a001/profiles/click/config.yaml"
)
V15_RESULTS = Path("/Users/teobun/arc-study/results/context-policy-multirepo-v15/a001")
V16_HIDDEN = Path("/Users/teobun/arc-study/runtime-assets/context-policy-multirepo-v12/hidden/click")


def test_v16_production_state_dynamic_import_registers_module_before_dataclasses() -> None:
    module = study_commands._load_production_state("v16")

    assert module.__name__ in sys.modules
    assert sys.modules[module.__name__] is module
    assert module.TaskIdentity("click", 1, "B3", "T001").key == "click/r1/B3/T001"


def test_v16_production_state_selector_is_explicit_and_fail_closed() -> None:
    assert study_commands._production_state_version("context-policy-multirepo-v16") == "v16"
    assert study_commands._production_state_version("context-policy-multirepo-v15") == "v15"
    with pytest.raises(ValueError, match="no production-state mapping"):
        study_commands._production_state_version("context-policy-multirepo-v99")


def test_real_run_plan_production_path_reaches_observer_and_stops_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the public CLI with production integration arguments, not a helper."""

    if not V15_PLAN.is_file() or not V15_PROFILE.is_file() or not V15_RESULTS.is_dir():
        pytest.skip("requires the previously frozen V15 execution apparatus")

    plan_payload = json.loads(V15_PLAN.read_text(encoding="utf-8"))
    plan_payload = _replace_v15(plan_payload)
    plan_payload["plan_digest"] = ""
    from eval.studies.preregistration import PreregisteredStudy

    plan = PreregisteredStudy.model_validate(plan_payload)
    plan = plan.model_copy(update={"plan_digest": compute_plan_digest(plan)})
    plan_path = save_preregistration(tmp_path / "click-context-policy-v16.json", plan)

    profile_text = V15_PROFILE.read_text(encoding="utf-8")
    profile_text = profile_text.replace("context-policy-multirepo-v15", "context-policy-multirepo-v16")
    profile_text = profile_text.replace("arc-v15", "arc-v16")
    profile_text = profile_text.replace("v15", "v16")
    profile_path = tmp_path / "click-config.yaml"
    profile_path.write_text(profile_text, encoding="utf-8")

    production_paths = {}
    for name in ("execution-manifest.json", "pre-execution-manifest.json", "checkpoint.json"):
        target = tmp_path / name
        shutil.copy2(V15_RESULTS / name, target)
        production_paths[name] = target
    production_paths["production-ledger.sqlite"] = tmp_path / "production-ledger.sqlite"
    production_state = study_commands._load_production_state("v16")
    ledger = production_state.ProductionLedger(
        production_paths["production-ledger.sqlite"],
        campaign_id="context-policy-multirepo-v16",
        attempt_id="a001",
        expected_tasks=162,
        checkpoint_path=production_paths["checkpoint.json"],
    )
    ledger.register(production_state.build_campaign_identities())
    ledger.close()

    observations = {"observer": 0, "run_manifest": 0, "provider": 0}
    real_loader = study_commands._load_production_state

    def instrumented_loader(version: str):
        module = real_loader(version)
        real_observer = module.ProductionTaskObserver

        class CountingObserver(real_observer):
            def __init__(self, *args, **kwargs):
                observations["observer"] += 1
                super().__init__(*args, **kwargs)

        module.ProductionTaskObserver = CountingObserver
        return module

    monkeypatch.setattr(study_commands, "_load_production_state", instrumented_loader)
    monkeypatch.setattr(study_commands, "build_agent", lambda profile: MockAgentAdapter(profile.name))

    async def stop_before_provider(self, *args, **kwargs):
        observations["run_manifest"] += 1
        raise RuntimeError("V16_PRE_PROVIDER_STOP")

    from eval.runners.experiment import ExperimentRunner

    monkeypatch.setattr(ExperimentRunner, "run_manifest", stop_before_provider)

    command = get_command(app)
    result = CliRunner().invoke(
        command,
        [
            "benchmark",
            "run-plan",
            str(plan_path),
            "--repo",
            "/Users/teobun/arc-study/repos/click",
            "--attempt-id",
            "a001",
            "--output-root",
            str(tmp_path / "results"),
            "--workspace-root",
            str(tmp_path / "workspace"),
            "--hidden-test-dir",
            str(V16_HIDDEN),
            "--production-ledger",
            str(production_paths["production-ledger.sqlite"]),
            "--production-manifest",
            str(production_paths["execution-manifest.json"]),
            "--production-checkpoint",
            str(production_paths["checkpoint.json"]),
            "--production-campaign-id",
            "context-policy-multirepo-v16",
            "--production-attempt-id",
            "a001",
            "--production-repository",
            "click",
            "--production-profile",
            str(profile_path),
        ],
    )

    assert result.exit_code == 2
    assert "V16_PRE_PROVIDER_STOP" in result.output
    assert observations == {"observer": 1, "run_manifest": 1, "provider": 0}
    assert not (tmp_path / "workspace" / f"{plan.study_id}-a001").exists()


def _replace_v15(value):
    if isinstance(value, str):
        return value.replace("context-policy-multirepo-v15", "context-policy-multirepo-v16").replace(
            "context-policy-click-v15", "context-policy-click-v16"
        ).replace("click-context-policy-v15", "click-context-policy-v16")
    if isinstance(value, list):
        return [_replace_v15(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_v15(item) for key, item in value.items()}
    return value
