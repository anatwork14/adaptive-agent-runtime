import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FINALIZER_PATH = (
    ROOT
    / "eval"
    / "campaigns"
    / "context-policy-multirepo-v1"
    / "finalize_campaign.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("campaign_finalizer", FINALIZER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _comparison(a: str, b: str, metric: str, mean: float, lower: float, upper: float):
    return {
        "baseline_a": a,
        "baseline_b": b,
        "metrics": {
            metric: {
                "repository_count": 3,
                "repetition_count": 18,
                "mean_delta": mean,
                "median_repository_delta": mean,
                "ci_lower": lower,
                "ci_upper": upper,
            }
        },
    }


def test_b7_orientation_preserves_interval_and_metric_direction() -> None:
    module = _module()

    resolved = module._orient_metric(
        _comparison("B3", "B7", "resolved_rate", -0.10, -0.20, -0.05),
        "resolved_rate",
    )
    assert resolved is not None
    assert resolved["comparison"] == "B7-B3"
    assert resolved["mean_delta"] == pytest.approx(0.10)
    assert resolved["ci_lower"] == pytest.approx(0.05)
    assert resolved["ci_upper"] == pytest.approx(0.20)
    assert resolved["preferred_direction"] == "higher"
    assert resolved["evidence"] == "direction_favors_B7"

    cost = module._orient_metric(
        _comparison("B5", "B7", "mean_cost_usd", 0.20, 0.10, 0.30),
        "mean_cost_usd",
    )
    assert cost is not None
    assert cost["comparison"] == "B7-B5"
    assert cost["mean_delta"] == pytest.approx(-0.20)
    assert cost["ci_lower"] == pytest.approx(-0.30)
    assert cost["ci_upper"] == pytest.approx(-0.10)
    assert cost["preferred_direction"] == "lower"
    assert cost["evidence"] == "direction_favors_B7"


def test_b7_orientation_marks_zero_crossing_as_uncertain() -> None:
    module = _module()
    item = module._orient_metric(
        _comparison("B7", "B3", "resolved_rate", 0.03, -0.02, 0.08),
        "resolved_rate",
    )
    assert item is not None
    assert item["evidence"] == "uncertain_ci_includes_zero"


def test_repository_export_hash_verification_fails_after_tamper(tmp_path) -> None:
    module = _module()
    export = tmp_path / "exports"
    export.mkdir()
    data = export / "tasks.csv"
    data.write_text("task_id,resolved\nT001,1\n", encoding="utf-8")
    digest = module._sha256_file(data)
    plan_digest = "a" * 64
    (export / "export_manifest.json").write_text(
        json.dumps(
            {
                "plan_digest": plan_digest,
                "files": {
                    "tasks_csv": {"path": "tasks.csv", "sha256": digest},
                },
            }
        ),
        encoding="utf-8",
    )

    verified = module._verify_repository_export(export, plan_digest)
    assert data in verified

    data.write_text("task_id,resolved\nT001,0\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="hash mismatch"):
        module._verify_repository_export(export, plan_digest)


def test_finalizer_rejects_artifact_paths_outside_attempt_root(tmp_path) -> None:
    module = _module()
    root = tmp_path / "attempt"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SystemExit, match="escapes campaign attempt root"):
        module._inside(root, outside, label="study")


def test_finalizer_script_compiles() -> None:
    source = FINALIZER_PATH.read_text(encoding="utf-8")
    compile(source, str(FINALIZER_PATH), "exec")
