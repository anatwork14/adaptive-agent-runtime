"""Unit tests for transactional IntegrationGate."""

import subprocess
from pathlib import Path

from runtime.gate import IntegrationGate
from state.events import EventStore
from state.models import GateStatus, PatchSubmission


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo_with_candidate(tmp_path: Path, content: str) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@local", "commit", "-m", "base")

    _git(repo, "checkout", "-b", "candidate")
    (repo / "feature.py").write_text(content, encoding="utf-8")
    _git(repo, "add", "feature.py")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@local", "commit", "-m", "candidate")
    candidate_sha = _git(repo, "rev-parse", "HEAD")
    diff = _git(repo, "show", "--format=", candidate_sha)
    _git(repo, "checkout", "main")
    return repo, candidate_sha, diff


def test_gate_accepts_and_integrates_real_candidate(tmp_path):
    repo, candidate_sha, diff = _repo_with_candidate(
        tmp_path,
        "def foo():\n    return 42\n",
    )
    store = EventStore(tmp_path / "gate_test.db")
    gate = IntegrationGate(store, "p_gate", repo, verification_level="V0")

    submission = PatchSubmission(
        patch_id="patch_1",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        candidate_commit_sha=candidate_sha,
        candidate_branch="candidate",
        diff=diff,
        summary="Added foo function",
    )

    result = gate.evaluate_submission(submission, staleness_score=0.1)
    assert result.status == GateStatus.ACCEPTED
    assert "G0_candidate_applied" in result.stages_passed
    assert "G1_static" in result.stages_passed
    assert "G4_integrated" in result.stages_passed
    assert (repo / "feature.py").exists()
    assert result.merged_commit_sha == _git(repo, "rev-parse", "HEAD")

    kinds = [e.kind for e in store.read_all(project_id="p_gate")]
    assert "gate.started" in kinds
    assert "gate.accepted" in kinds
    store.close()


def test_gate_rejects_stale_patch_before_integration(tmp_path):
    store = EventStore(tmp_path / "gate_stale.db")
    gate = IntegrationGate(store, "p_gate", tmp_path, verification_level="V0")

    submission = PatchSubmission(
        patch_id="patch_stale",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        candidate_commit_sha="deadbeef",
        diff="",
        summary="stale candidate",
    )

    result = gate.evaluate_submission(submission, staleness_score=0.95)
    assert result.status == GateStatus.REJECTED
    assert result.rejection_stage == "G0_STALE"
    assert "stale" in (result.error_detail or "").lower()

    kinds = [e.kind for e in store.read_all(project_id="p_gate")]
    assert "gate.rejected" in kinds
    store.close()


def test_gate_rejects_security_violation_in_v2(tmp_path):
    repo, candidate_sha, diff = _repo_with_candidate(
        tmp_path,
        'api_key = "GITHUB_TOKEN_TEST_PLACEHOLDER"\n',
    )
    store = EventStore(tmp_path / "gate_sec.db")
    gate = IntegrationGate(store, "p_gate", repo, verification_level="V2")

    submission = PatchSubmission(
        patch_id="patch_leak",
        task_id="t1",
        agent_id="agent_1",
        context_id="ctx_1",
        dispatch_state_version=1,
        candidate_commit_sha=candidate_sha,
        candidate_branch="candidate",
        diff=diff,
        summary="Hardcoded token",
    )

    result = gate.evaluate_submission(submission, staleness_score=0.0)
    assert result.status == GateStatus.REJECTED
    assert result.rejection_stage == "V2_REVIEW"
    assert not (repo / "feature.py").exists()
    store.close()
