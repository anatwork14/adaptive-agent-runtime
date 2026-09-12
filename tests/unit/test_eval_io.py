"""Round-trip tests for benchmark manifests and immutable result records."""

from __future__ import annotations

from pathlib import Path

from eval.io import (
    load_manifest,
    read_measurements_jsonl,
    write_measurements_jsonl,
    write_summary_json,
)
from eval.models import EvaluationSummary, TaskMeasurement


def test_yaml_manifest_loads_with_matched_budget(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.yaml"
    path.write_text(
        """
benchmark_id: smoke
baseline: B7
seed: 1
agent_profile: mock
repo_commit: abcdef1
context_token_budget: 4000
tasks:
  - task_id: T001
    goal: fix edge case
    token_budget: 4000
""".strip()
        + "\n",
        encoding="utf-8",
    )

    manifest = load_manifest(path)
    assert manifest.benchmark_id == "smoke"
    assert manifest.tasks[0].token_budget == 4000


def test_measurement_jsonl_round_trip_preserves_null_telemetry(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    item = TaskMeasurement(
        benchmark_id="smoke",
        baseline="B7",
        task_id="T001",
        agent_profile="mock",
        repo_commit="abcdef1",
        resolved=True,
        gate_status="accepted",
        context_tokens=1234,
        provider_tokens=None,
        cost_usd=None,
        cost_observed=False,
        token_usage_observed=False,
        end_to_end_latency_ms=42.0,
        event_start=3,
        event_end=9,
    )

    write_measurements_jsonl(path, [item])
    restored = read_measurements_jsonl(path)

    assert restored == [item]
    assert '"cost_usd":null' in path.read_text(encoding="utf-8")


def test_summary_json_is_stable_and_explicit_about_coverage(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = EvaluationSummary(
        benchmark_id="smoke",
        baseline="B7",
        total_tasks=2,
        resolved_count=1,
        resolved_rate=0.5,
        mean_cost_usd=None,
        total_cost_usd=None,
        cost_coverage=0.0,
        token_coverage=0.0,
    )

    write_summary_json(path, summary)
    text = path.read_text(encoding="utf-8")
    assert '"cost_coverage": 0.0' in text
    assert '"mean_cost_usd": null' in text
