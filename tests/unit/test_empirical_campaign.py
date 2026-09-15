import json
import shlex
from pathlib import Path

from eval.comparison import validate_comparable_manifests
from eval.io import load_manifest

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / "eval" / "campaigns" / "context-policy-multirepo-v1"
EXPECTED = {
    "click": ("context-policy-click-v1", "6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1"),
    "httpx": ("context-policy-httpx-v1", "b5addb64f0161ff6bfe94c124ef76f6a1fba5254"),
    "python-dotenv": (
        "context-policy-python-dotenv-v1",
        "a00cb2eed0704cd6d2071b2004c37e95ccc86ee5",
    ),
}


def test_campaign_manifest_triplets_are_valid_and_matched() -> None:
    for repo_name, (benchmark_id, repo_commit) in EXPECTED.items():
        manifests = [
            load_manifest(CAMPAIGN / repo_name / f"{baseline.lower()}.yaml")
            for baseline in ("B3", "B5", "B7")
        ]
        assert [manifest.baseline for manifest in manifests] == ["B3", "B5", "B7"]
        assert {manifest.benchmark_id for manifest in manifests} == {benchmark_id}
        assert {manifest.repo_commit for manifest in manifests} == {repo_commit}
        assert {manifest.model for manifest in manifests} == {"gpt-5.3-codex"}
        assert {manifest.context_token_budget for manifest in manifests} == {12000}
        assert {manifest.hard_task_usd for manifest in manifests} == {2.0}
        assert all(
            [task.task_id for task in manifest.tasks] == ["T001", "T002", "T003"]
            for manifest in manifests
        )
        for other in manifests[1:]:
            validate_comparable_manifests(manifests[0], other)


def test_campaign_freeze_contract_matches_manifests() -> None:
    contract = json.loads((CAMPAIGN / "campaign_contract.json").read_text(encoding="utf-8"))
    assert contract["campaign_id"] == "context-policy-multirepo-v1"
    assert contract["shared_protocol"]["verification_level"] == "V1"
    assert contract["shared_protocol"]["repeats"] == 6
    assert contract["shared_protocol"]["hard_project_usd"] == 350.0

    profile = contract["provider_profile"]
    assert profile["provider"] == "codex"
    assert profile["model"] == "gpt-5.3-codex"
    argv = shlex.split(profile["command_override"])
    assert argv[:4] == ["codex", "exec", "--full-auto", "--model"]
    assert "model_reasoning_effort=\"high\"" in argv
    assert argv[-1] == "-"

    treatments = contract["treatments"]
    assert treatments["B3"]["memory_policy"] == "static_no_memory"
    assert treatments["B5"]["memory_policy"] == "naive_vector_topk"
    assert treatments["B5"]["top_k"] == 5
    assert treatments["B5"]["validity_enforced"] is False
    assert treatments["B7"]["memory_policy"] == "provenance_aware_adaptive"
    assert treatments["B7"]["validity_enforced"] is True
    assert treatments["B7"]["root_task_generic_episode_fallback"] is True
    assert "declared dependency" in treatments["B7"]["episodic_dependency_scope"]
    assert "before provider execution" in contract["identification"]["b5_vs_b7"]

    for repo_name, (benchmark_id, repo_commit) in EXPECTED.items():
        repo_contract = contract["repositories"][repo_name]
        assert repo_contract["benchmark_id"] == benchmark_id
        assert repo_contract["commit"] == repo_commit
        hidden_digest = repo_contract["hidden_tree_sha256"]
        assert len(hidden_digest) == 64
        int(hidden_digest, 16)


def test_campaign_freeze_and_execution_scripts_compile() -> None:
    for name in ("runtime_lock.py", "freeze_campaign.py", "execute_campaign.py"):
        source = (CAMPAIGN / name).read_text(encoding="utf-8")
        compile(source, str(CAMPAIGN / name), "exec")
