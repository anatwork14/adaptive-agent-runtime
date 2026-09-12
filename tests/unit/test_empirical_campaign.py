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
        manifests = [load_manifest(CAMPAIGN / repo_name / f"{baseline.lower()}.yaml") for baseline in ("B3", "B5", "B7")]
        assert [manifest.baseline for manifest in manifests] == ["B3", "B5", "B7"]
        assert {manifest.benchmark_id for manifest in manifests} == {benchmark_id}
        assert {manifest.repo_commit for manifest in manifests} == {repo_commit}
        assert {manifest.model for manifest in manifests} == {"gpt-5.3-codex"}
        assert {manifest.context_token_budget for manifest in manifests} == {12000}
        assert {manifest.hard_task_usd for manifest in manifests} == {2.0}
        assert all([task.task_id for task in manifest.tasks] == ["T001", "T002", "T003"] for manifest in manifests)
        for other in manifests[1:]:
            validate_comparable_manifests(manifests[0], other)


def test_runtime_lock_script_compiles() -> None:
    source = (CAMPAIGN / "runtime_lock.py").read_text(encoding="utf-8")
    compile(source, str(CAMPAIGN / "runtime_lock.py"), "exec")
