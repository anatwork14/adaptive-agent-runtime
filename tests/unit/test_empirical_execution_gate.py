import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_GATE_PATH = (
    ROOT
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v1"
    / "execute_campaign.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("campaign_execution_gate", EXECUTION_GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attempt_id_rejects_paths_and_accepts_explicit_tokens() -> None:
    module = _module()
    for valid in ("a001", "retry-02", "pilot.final_1"):
        module._validate_attempt_id(valid)

    for invalid in ("", "a 001", "../a001", "a001/child", "/tmp/a001"):
        with pytest.raises(SystemExit, match="attempt-id"):
            module._validate_attempt_id(invalid)


def test_result_and_workspace_roots_must_be_outside_source_repositories(tmp_path) -> None:
    module = _module()
    source = tmp_path / "source"
    source.mkdir()
    safe = tmp_path / "results"

    assert module._require_external(safe, [source], label="results-root") == safe.resolve()
    with pytest.raises(SystemExit, match="outside source repository"):
        module._require_external(source / "results", [source], label="results-root")


def test_study_directory_is_deterministic_from_frozen_plan(tmp_path) -> None:
    module = _module()
    plan = SimpleNamespace(
        benchmark_id="context-policy-click-v1",
        study_id="click-context-policy-v1",
    )
    expected = (
        tmp_path
        / "context-policy-click-v1"
        / "studies"
        / "click-context-policy-v1-a001"
    )
    assert module._study_dir(tmp_path, plan, "a001") == expected


def test_execution_gate_script_compiles() -> None:
    source = EXECUTION_GATE_PATH.read_text(encoding="utf-8")
    compile(source, str(EXECUTION_GATE_PATH), "exec")
