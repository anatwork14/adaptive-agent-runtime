import json
from pathlib import Path

import pytest

from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.studies.meta import (
    aggregate_meta_study,
    compute_meta_plan_digest,
    create_meta_preregistration,
    load_meta_preregistration,
    save_meta_preregistration,
)
from eval.studies.preregistration import (
    PreregisteredStudy,
    StudyDesign,
    StudyRuntimeContract,
    compute_plan_digest,
)

BASELINES = ("B3", "B5", "B7")


def _plan(benchmark_id: str, commit_char: str = "a") -> PreregisteredStudy:
    task = EvaluationTaskSpec(
        task_id="T001",
        goal="make the change",
        files=["src/app.py"],
        acceptance=["tests pass"],
        token_budget=100,
    )
    manifests = [
        BenchmarkManifest(
            benchmark_id=benchmark_id,
            baseline=baseline,
            seed=11,
            agent_profile="builder",
            model="model-x",
            repo_commit=commit_char * 40,
            context_token_budget=100,
            hard_task_usd=1.0,
            tasks=[task],
        )
        for baseline in BASELINES
    ]
    raw = PreregisteredStudy(
        study_id=f"{benchmark_id}-plan",
        benchmark_id=benchmark_id,
        created_at_utc="2026-09-12T00:00:00+00:00",
        canonical_repo_commit=commit_char * 40,
        manifests=manifests,
        design=StudyDesign(repeats=3, bootstrap_samples=100, ci=0.95),
        runtime=StudyRuntimeContract(
            agent_profile="builder",
            provider="mock-provider",
            model="model-x",
            hard_project_usd=10.0,
        ),
        planned_comparisons=["B3-B5", "B3-B7", "B5-B7"],
    )
    return raw.model_copy(update={"plan_digest": compute_plan_digest(raw)})


def _write_study(
    root: Path,
    plan: PreregisteredStudy,
    *,
    b3: list[float],
    b5: list[float],
    b7: list[float],
) -> Path:
    root.mkdir(parents=True)
    values = {"B3": b3, "B5": b5, "B7": b7}
    repetitions = []
    for index in range(len(b3)):
        repeat_rel = Path("repeats") / f"r{index + 1:03d}"
        repeat_root = root / repeat_rel
        baselines = {}
        for baseline in BASELINES:
            baseline_rel = baseline.lower()
            baseline_root = repeat_root / baseline_rel
            baseline_root.mkdir(parents=True, exist_ok=True)
            resolved = values[baseline][index]
            summary = {
                "benchmark_id": plan.benchmark_id,
                "baseline": baseline,
                "total_tasks": 2,
                "resolved_count": int(round(resolved * 2)),
                "resolved_rate": resolved,
                "mean_context_tokens": {"B3": 50.0, "B5": 80.0, "B7": 70.0}[baseline],
                "mean_provider_tokens": {"B3": 100.0, "B5": 120.0, "B7": 110.0}[baseline],
                "mean_cost_usd": {"B3": 0.10, "B5": 0.12, "B7": 0.11}[baseline],
                "total_cost_usd": 0.2,
                "cost_coverage": 1.0,
                "token_coverage": 1.0,
                "p95_end_to_end_latency_ms": {"B3": 1000.0, "B5": 1200.0, "B7": 900.0}[baseline],
                "p95_retrieval_latency_ms": None,
                "stale_delivery_rate": {"B3": 0.0, "B5": 0.4, "B7": 0.0}[baseline],
            }
            (baseline_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            baselines[baseline] = {"artifact_dir": baseline_rel}
        (repeat_root / "paired_run.json").write_text(
            json.dumps({"baselines": baselines}), encoding="utf-8"
        )
        repetitions.append(
            {
                "run_id": f"{plan.study_id}-r{index + 1:03d}",
                "execution_order": list(BASELINES),
                "artifact_dir": repeat_rel.as_posix(),
            }
        )

    (root / "study.json").write_text(
        json.dumps(
            {
                "study_id": f"{plan.study_id}-a001",
                "benchmark_id": plan.benchmark_id,
                "base_commit": plan.canonical_repo_commit,
                "repeat_count": len(b3),
                "repetitions": repetitions,
            }
        ),
        encoding="utf-8",
    )
    (root / "provenance.json").write_text(
        json.dumps(
            {
                "agent_profile": plan.runtime.agent_profile,
                "declared_model": plan.runtime.model,
                "extra": {
                    "provider": plan.runtime.provider,
                    "preregistered": True,
                    "plan_digest": plan.plan_digest,
                    "attempt_id": "a001",
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def test_meta_preregistration_is_self_digesting_and_rejects_protocol_drift(tmp_path: Path) -> None:
    left = _plan("repo-a", "a")
    right = _plan("repo-b", "b")
    meta = create_meta_preregistration(
        [left, right],
        meta_id="meta-01",
        bootstrap_samples=200,
        random_seed=9,
        created_at_utc="2026-09-12T00:00:00+00:00",
    )
    assert meta.plan_digest == compute_meta_plan_digest(meta)

    path = tmp_path / "meta.json"
    save_meta_preregistration(path, meta)
    assert load_meta_preregistration(path).plan_digest == meta.plan_digest

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ci"] = 0.9
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_meta_preregistration(path)

    drift = _plan("repo-c", "c")
    drift = drift.model_copy(
        update={"runtime": drift.runtime.model_copy(update={"model": "different-model"})}
    )
    drift = drift.model_copy(update={"plan_digest": compute_plan_digest(drift)})
    with pytest.raises(ValueError, match="protocol differs on model"):
        create_meta_preregistration([left, drift], meta_id="bad")


def test_hierarchical_meta_analysis_uses_repository_clusters_and_frozen_selection(
    tmp_path: Path,
) -> None:
    plan_a = _plan("repo-a", "a")
    plan_b = _plan("repo-b", "b")
    meta = create_meta_preregistration(
        [plan_a, plan_b],
        meta_id="meta-01",
        bootstrap_samples=500,
        ci=0.95,
        random_seed=3,
        created_at_utc="2026-09-12T00:00:00+00:00",
    )
    study_a = _write_study(
        tmp_path / "study-a",
        plan_a,
        b3=[0.4, 0.5, 0.6],
        b5=[0.5, 0.6, 0.7],
        b7=[0.8, 0.8, 0.9],
    )
    study_b = _write_study(
        tmp_path / "study-b",
        plan_b,
        b3=[0.3, 0.4, 0.5],
        b5=[0.4, 0.5, 0.6],
        b7=[0.7, 0.8, 0.8],
    )

    result = aggregate_meta_study(
        meta,
        [study_b, study_a],
        output_dir=tmp_path / "meta-out",
    )
    assert result.repository_count == 2
    pair = next(
        item
        for item in result.comparisons
        if (item.baseline_a, item.baseline_b) == ("B3", "B7")
    )
    resolved = pair.metrics["resolved_rate"]
    assert resolved.repository_count == 2
    assert resolved.repetition_count == 6
    assert resolved.mean_delta is not None and resolved.mean_delta < 0.0
    assert resolved.ci_upper is not None and resolved.ci_upper < 0.0
    assert pair.repository_wins_b == 2
    assert (result.artifact_dir / "meta_study.json").is_file()
    assert (result.artifact_dir / "repository_effects.csv").is_file()
    assert (result.artifact_dir / "meta_export_manifest.json").is_file()

    with pytest.raises(ValueError, match="expected 2 repositories"):
        aggregate_meta_study(
            meta,
            [study_a],
            output_dir=tmp_path / "missing-out",
        )
