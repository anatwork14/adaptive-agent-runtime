from __future__ import annotations

import pytest

from context.compiler import ContextPacket
from eval.comparison import validate_comparable_manifests
from eval.models import BenchmarkManifest, EvaluationTaskSpec
from eval.runners.paired import blind_context_for_provider


def _manifest(baseline: str = "B3", **overrides) -> BenchmarkManifest:
    payload = dict(
        benchmark_id="paired-contract",
        baseline=baseline,
        seed=7,
        agent_profile="builder",
        model="model-x",
        repo_commit="abcdef1",
        context_token_budget=4000,
        hard_task_usd=1.0,
        project_constraints=["offline"],
        tasks=[
            EvaluationTaskSpec(
                task_id="T001",
                goal="first",
                task_type="implementation",
                required_capabilities=["implementation"],
                files=["src/a.py"],
                symbols=["parse"],
                acceptance=["tests pass"],
                token_budget=4000,
            ),
            EvaluationTaskSpec(
                task_id="T002",
                goal="second",
                dependencies=["T001"],
                files=["src/b.py"],
                token_budget=4000,
            ),
        ],
    )
    payload.update(overrides)
    return BenchmarkManifest(**payload)


def test_manifest_rejects_forward_dependency() -> None:
    with pytest.raises(ValueError, match="earlier sequence tasks"):
        BenchmarkManifest(
            benchmark_id="bad",
            baseline="B3",
            agent_profile="builder",
            repo_commit="abcdef1",
            context_token_budget=4000,
            tasks=[
                EvaluationTaskSpec(
                    task_id="T001",
                    goal="first",
                    dependencies=["T002"],
                    token_budget=4000,
                ),
                EvaluationTaskSpec(task_id="T002", goal="second", token_budget=4000),
            ],
        )


def test_comparison_rejects_constraint_or_dependency_drift() -> None:
    left = _manifest("B3")
    right = _manifest("B7")
    validate_comparable_manifests(left, right)

    with pytest.raises(ValueError, match="project_constraints"):
        validate_comparable_manifests(
            left,
            _manifest("B7", project_constraints=["network-ok"]),
        )

    changed = right.model_copy(deep=True)
    changed.tasks[1].dependencies = []
    with pytest.raises(ValueError, match="dependencies"):
        validate_comparable_manifests(left, changed)


def test_provider_blinding_removes_treatment_metadata_but_keeps_semantics() -> None:
    packet = ContextPacket(
        context_id="CTX_REAL",
        project_id="project-secret",
        task_id="T001",
        agent_id="builder",
        state_version=44,
        compiled_event=45,
        context_policy="B5",
        goal="preserve parser compatibility",
        decisions=[
            {
                "memory_id": "M_DEC_1",
                "text": "Keep the parser API stable",
                "source_events": [10],
                "status": "superseded",
            }
        ],
        failures=[{"memory_id": "M_FAIL_1", "text": "Old failure", "status": "active"}],
        episodes=[{"text": "Task Summary [T000]: introduced the shared parser abstraction"}],
        leases=[{"resource": "parser.py", "fencing_token": 99}],
        risk_flags=["STALE_MEMORY_DELIVERED"],
        context_token_count=777,
        memory_ids=["M_DEC_1", "M_TSUM_1"],
        stale_memory_ids=["M_DEC_1"],
        retrieval_strategies=["naive_vector_topk"],
        digest="sha256:secret",
    )

    blinded = blind_context_for_provider(packet)

    assert blinded.goal == packet.goal
    assert blinded.decisions == [{"text": "Keep the parser API stable"}]
    assert blinded.failures == [{"text": "Old failure"}]
    assert blinded.episodes == [
        {"text": "Task Summary [T000]: introduced the shared parser abstraction"}
    ]
    assert blinded.context_policy == "BLINDED"
    assert blinded.project_id == "benchmark"
    assert blinded.state_version == 0
    assert blinded.compiled_event == 0
    assert blinded.memory_ids == []
    assert blinded.stale_memory_ids == []
    assert blinded.retrieval_strategies == []
    assert blinded.risk_flags == []
    assert blinded.leases == []
    assert blinded.digest == ""
