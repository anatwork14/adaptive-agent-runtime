import csv
import json

from eval.models import TaskMeasurement
from eval.studies.export import export_study_tidy


def test_tidy_export_flattens_completed_repeated_study(tmp_path) -> None:
    study_root = tmp_path / "study"
    repeat_root = study_root / "repeats" / "bench" / "run-001"
    b3_dir = repeat_root / "b3"
    b5_dir = repeat_root / "b5"
    b3_dir.mkdir(parents=True)
    b5_dir.mkdir(parents=True)

    study = {
        "study_id": "study-001",
        "benchmark_id": "bench",
        "base_commit": "a" * 40,
        "repeat_count": 1,
        "repeat_seeds": [11],
        "repetitions": [
            {
                "run_id": "run-001",
                "execution_order": ["B5", "B3"],
                "artifact_dir": "repeats/bench/run-001",
            }
        ],
    }
    (study_root / "study.json").write_text(json.dumps(study), encoding="utf-8")
    (study_root / "provenance.json").write_text(
        json.dumps({"extra": {"plan_digest": "plan123"}}),
        encoding="utf-8",
    )
    (study_root / "aggregates.json").write_text(
        json.dumps(
            [
                {
                    "baseline_a": "B3",
                    "baseline_b": "B5",
                    "repetitions": 1,
                    "wins_a": 1,
                    "wins_b": 0,
                    "ties": 0,
                    "resolved_rate_delta": {
                        "sample_count": 1,
                        "mean_delta": 1.0,
                        "median_delta": 1.0,
                        "ci_lower": 1.0,
                        "ci_upper": 1.0,
                    },
                    "mean_context_tokens_delta": {
                        "sample_count": 1,
                        "mean_delta": -100.0,
                        "median_delta": -100.0,
                        "ci_lower": -100.0,
                        "ci_upper": -100.0,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    paired = {
        "baselines": {
            "B3": {
                "initial_commit": "a" * 40,
                "final_commit": "b" * 40,
                "event_count": 10,
                "artifact_dir": "b3",
            },
            "B5": {
                "initial_commit": "a" * 40,
                "final_commit": "c" * 40,
                "event_count": 11,
                "artifact_dir": "b5",
            },
        }
    }
    (repeat_root / "paired_run.json").write_text(json.dumps(paired), encoding="utf-8")

    for baseline_dir, baseline, resolved, mean_context in (
        (b3_dir, "B3", True, 900.0),
        (b5_dir, "B5", False, 1000.0),
    ):
        summary = {
            "benchmark_id": "bench",
            "baseline": baseline,
            "total_tasks": 1,
            "resolved_count": int(resolved),
            "resolved_rate": float(resolved),
            "mean_context_tokens": mean_context,
            "mean_provider_tokens": None,
            "mean_cost_usd": None,
            "total_cost_usd": None,
            "cost_coverage": 0.0,
            "token_coverage": 0.0,
            "p95_end_to_end_latency_ms": 100.0,
            "p95_retrieval_latency_ms": None,
            "stale_delivery_rate": 0.0,
        }
        (baseline_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        measurement = TaskMeasurement(
            benchmark_id="bench",
            baseline=baseline,
            task_id="T001",
            agent_profile="builder",
            model="mock-model",
            seed=11,
            repo_commit="a" * 40,
            resolved=resolved,
            gate_status="accepted" if resolved else "rejected",
            context_tokens=int(mean_context),
            context_hard_budget=4000,
            end_to_end_latency_ms=100.0,
            event_start=1,
            event_end=5,
        )
        (baseline_dir / "measurements.jsonl").write_text(
            json.dumps(measurement.model_dump(mode="json")) + "\n",
            encoding="utf-8",
        )

    outputs = export_study_tidy(study_root)
    assert outputs["tasks_csv"].is_file()
    assert outputs["pairs_jsonl"].is_file()

    with outputs["tasks_csv"].open(encoding="utf-8", newline="") as handle:
        task_rows = list(csv.DictReader(handle))
    with outputs["repetitions_csv"].open(encoding="utf-8", newline="") as handle:
        repetition_rows = list(csv.DictReader(handle))
    with outputs["pairs_csv"].open(encoding="utf-8", newline="") as handle:
        pair_rows = list(csv.DictReader(handle))

    assert len(task_rows) == 2
    assert {row["order_position"] for row in task_rows} == {"1", "2"}
    assert len(repetition_rows) == 2
    assert {row["baseline"] for row in repetition_rows} == {"B3", "B5"}
    assert {row["metric"] for row in pair_rows} == {
        "resolved_rate",
        "mean_context_tokens",
    }

    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    assert manifest["plan_digest"] == "plan123"
    assert manifest["row_counts"] == {"tasks": 2, "repetitions": 2, "pairs": 2}
    assert all(item["sha256"] for item in manifest["files"].values())
