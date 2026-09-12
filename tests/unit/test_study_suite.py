import json
from dataclasses import asdict

import pytest

from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.studies.preregistration import (
    PreregisteredStudy,
    StudyDesign,
    StudyRuntimeContract,
    compute_plan_digest,
)
from eval.studies.suite import (
    aggregate_suite_studies,
    compute_suite_digest,
    create_suite,
    load_suite,
    save_suite,
)


def _plan(repo_id: str, commit: str) -> PreregisteredStudy:
    task = EvaluationTaskSpec(
        task_id="T001",
        goal=f"Update {repo_id}",
        files=["app.py"],
        acceptance=["works"],
        token_budget=4000,
    )
    manifests = [
        BenchmarkManifest(
            benchmark_id=f"bench-{repo_id}",
            baseline=baseline,
            seed=7,
            agent_profile="builder",
            model="provider-model",
            repo_commit=commit,
            context_token_budget=4000,
            hard_task_usd=1.0,
            tasks=[task],
        )
        for baseline in ("B3", "B7")
    ]
    plan = PreregisteredStudy(
        study_id=f"study-{repo_id}",
        benchmark_id=f"bench-{repo_id}",
        created_at_utc="2026-09-12T00:00:00+00:00",
        canonical_repo_commit=commit,
        manifests=manifests,
        design=StudyDesign(repeats=2, bootstrap_samples=100, ci=0.95),
        runtime=StudyRuntimeContract(
            agent_profile="builder",
            provider="codex",
            model="provider-model",
            profile_role="builder",
            profile_capabilities=["implementation", "test"],
            visible_test_cmd=["python", "-m", "pytest", "-q"],
            hard_project_usd=10.0,
            verification_level="V0",
        ),
        planned_comparisons=["B3-B7"],
    )
    return plan.model_copy(update={"plan_digest": compute_plan_digest(plan)})


def _write_study(root, plan: PreregisteredStudy, deltas: list[float]) -> None:
    root.mkdir(parents=True)
    repetitions = []
    for index, delta in enumerate(deltas, start=1):
        repeat_rel = f"repeats/{plan.benchmark_id}/run-{index:03d}"
        repeat_root = root / repeat_rel
        b3 = repeat_root / "b3"
        b7 = repeat_root / "b7"
        b3.mkdir(parents=True)
        b7.mkdir(parents=True)
        b7_resolved = 0.0
        b3_resolved = delta
        for directory, baseline, resolved, context, stale in (
            (b3, "B3", b3_resolved, 1000.0, 0.0),
            (b7, "B7", b7_resolved, 800.0, 0.0),
        ):
            summary = {
                "benchmark_id": plan.benchmark_id,
                "baseline": baseline,
                "total_tasks": 2,
                "resolved_count": int(resolved * 2),
                "resolved_rate": resolved,
                "mean_context_tokens": context,
                "mean_provider_tokens": 500.0,
                "mean_cost_usd": 0.05,
                "total_cost_usd": 0.1,
                "cost_coverage": 1.0,
                "token_coverage": 1.0,
                "p95_end_to_end_latency_ms": 200.0,
                "p95_retrieval_latency_ms": 5.0,
                "stale_delivery_rate": stale,
            }
            (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        paired = {
            "baselines": {
                "B3": {
                    "initial_commit": plan.canonical_repo_commit,
                    "final_commit": "c" * 40,
                    "event_count": 10,
                    "artifact_dir": "b3",
                },
                "B7": {
                    "initial_commit": plan.canonical_repo_commit,
                    "final_commit": "d" * 40,
                    "event_count": 10,
                    "artifact_dir": "b7",
                },
            }
        }
        (repeat_root / "paired_run.json").write_text(json.dumps(paired), encoding="utf-8")
        repetitions.append(
            {
                "run_id": f"run-{index:03d}",
                "execution_order": ["B3", "B7"],
                "artifact_dir": repeat_rel,
            }
        )

    study = {
        "study_id": f"{plan.study_id}-a001",
        "benchmark_id": plan.benchmark_id,
        "base_commit": plan.canonical_repo_commit,
        "repeat_count": plan.design.repeats,
        "repeat_seeds": [11, 12],
        "order_schedule": plan.design.order_schedule,
        "repetitions": repetitions,
        "aggregate_pairs": ["B3-B7"],
    }
    provenance = {
        "study_id": study["study_id"],
        "benchmark_id": plan.benchmark_id,
        "base_commit": plan.canonical_repo_commit,
        "base_seed": 7,
        "order_schedule": plan.design.order_schedule,
        "repeat_seeds": [11, 12],
        "repeat_count": plan.design.repeats,
        "n_bootstraps": plan.design.bootstrap_samples,
        "ci": plan.design.ci,
        "agent_profile": plan.runtime.agent_profile,
        "declared_model": plan.runtime.model,
        "runtime": {
            "verification_level": plan.runtime.verification_level,
            "visible_test_cmd": plan.runtime.visible_test_cmd,
            "hard_project_usd": plan.runtime.hard_project_usd,
            "hidden_tests_enabled": False,
        },
        "extra": {
            "preregistered": True,
            "preregistered_study_id": plan.study_id,
            "plan_digest": plan.plan_digest,
            "attempt_id": "a001",
        },
    }
    (root / "study.json").write_text(json.dumps(study), encoding="utf-8")
    (root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")


def test_suite_digest_protocol_validation_and_hierarchical_aggregation(tmp_path) -> None:
    plan_a = _plan("repo-a", "a" * 40)
    plan_b = _plan("repo-b", "b" * 40)
    suite = create_suite(
        {"repo-a": plan_a, "repo-b": plan_b},
        suite_id="suite-001",
        bootstrap_samples=500,
        ci=0.95,
        created_at_utc="2026-09-12T00:00:00+00:00",
    )
    suite_path = save_suite(tmp_path / "suite.json", suite)
    loaded = load_suite(suite_path)
    assert loaded.suite_digest == suite.suite_digest

    study_a = tmp_path / "study-a"
    study_b = tmp_path / "study-b"
    _write_study(study_a, plan_a, [1.0, 0.5])
    _write_study(study_b, plan_b, [0.5, 0.0])

    result = aggregate_suite_studies(
        loaded,
        {"repo-a": study_a, "repo-b": study_b},
        output_dir=tmp_path / "aggregate",
    )
    assert result.repository_count == 2
    assert len(result.aggregates) == 1
    resolved = result.aggregates[0].resolved_rate_delta
    assert resolved.repository_count == 2
    assert resolved.repetition_pair_count == 4
    assert resolved.mean_delta == pytest.approx(0.5)
    assert resolved.median_repository_delta == pytest.approx(0.5)
    assert resolved.ci_lower is not None
    assert resolved.ci_upper is not None
    assert (result.artifact_dir / "repository_effects.csv").is_file()
    assert (result.artifact_dir / "hierarchical_effects.csv").is_file()
    provenance = json.loads(
        (result.artifact_dir / "suite_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["suite_digest"] == suite.suite_digest
    assert set(provenance["members"]) == {"repo-a", "repo-b"}

    payload = json.loads(suite_path.read_text(encoding="utf-8"))
    payload["design"]["bootstrap_samples"] = 1
    suite_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="suite digest mismatch"):
        load_suite(suite_path)


def test_suite_rejects_protocol_drift() -> None:
    plan_a = _plan("repo-a", "a" * 40)
    plan_b = _plan("repo-b", "b" * 40)
    drifted = plan_b.model_copy(
        update={"design": plan_b.design.model_copy(update={"repeats": 3})},
        deep=True,
    )
    drifted = drifted.model_copy(update={"plan_digest": compute_plan_digest(drifted)})
    with pytest.raises(ValueError, match="treatment protocol differs"):
        create_suite({"repo-a": plan_a, "repo-b": drifted}, suite_id="bad-suite")


def test_suite_study_mapping_and_plan_digest_fail_closed(tmp_path) -> None:
    plan_a = _plan("repo-a", "a" * 40)
    plan_b = _plan("repo-b", "b" * 40)
    suite = create_suite({"repo-a": plan_a, "repo-b": plan_b}, suite_id="suite-002")
    with pytest.raises(ValueError, match="mapping mismatch"):
        aggregate_suite_studies(
            suite,
            {"repo-a": tmp_path / "missing"},
            output_dir=tmp_path / "out",
        )

    invalid = plan_b.model_copy(update={"plan_digest": "0" * 64})
    with pytest.raises(ValueError, match="invalid plan_digest"):
        create_suite({"repo-a": plan_a, "repo-b": invalid}, suite_id="suite-003")
