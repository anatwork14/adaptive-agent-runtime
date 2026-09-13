"""Serialized integration gate that verifies the exact candidate commit."""

import shutil
import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, List, Optional

from runtime.git import arc_git_write_args, arc_git_write_env
from state.events import EventStore
from state.models import GateResult, GateStatus, PatchSubmission
from verification.adversarial_tests import AdversarialTestRunner
from verification.reviewer import CodeReviewer
from verification.static import StaticVerifier


class IntegrationGateError(RuntimeError):
    """Raised when the integration gate cannot establish a safe git operation."""


class IntegrationGate:
    """Serialize candidate integration through an isolated verification worktree.

    The gate consumes an immutable candidate commit, cherry-picks it onto a
    temporary worktree at the current integration HEAD, verifies that exact
    tree, then cherry-picks the same commit into the integration branch only
    after all configured checks pass.
    """

    def __init__(
        self,
        event_store: EventStore,
        project_id: str,
        workspace_path: str | Path,
        verification_level: str = "V0",
        visible_test_harness: Optional[dict[str, Any]] = None,
    ) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self.workspace_path = Path(workspace_path).resolve()
        self.verification_level = verification_level
        self.visible_test_harness = dict(visible_test_harness or {})
        self.gate_root = (
            self.workspace_path.parent / ".arc-runtime" / self.workspace_path.name / "gates"
        )
        self.gate_root.mkdir(parents=True, exist_ok=True)
        self.reviewer = CodeReviewer()

    def _git(
        self,
        args: List[str],
        *,
        cwd: Optional[Path] = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd or self.workspace_path),
                capture_output=True,
                text=True,
                check=check,
                env=dict(env) if env is not None else None,
            )
        except FileNotFoundError as exc:
            raise IntegrationGateError("git executable is required for integration") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise IntegrationGateError(f"git {' '.join(args)} failed: {detail}") from exc

    def _ensure_clean_integration_tree(self) -> None:
        result = self._git(["status", "--porcelain"], check=False)
        if result.stdout.strip():
            raise IntegrationGateError(
                "integration worktree is dirty; ARC requires a clean single-writer tree: "
                + "; ".join(result.stdout.splitlines()[:10])
            )

    def _create_gate_worktree(self, gate_run_id: str) -> Path:
        gate_path = self.gate_root / gate_run_id
        if gate_path.exists():
            shutil.rmtree(gate_path, ignore_errors=True)
        self._git(["worktree", "add", "--detach", str(gate_path), "HEAD"])
        return gate_path

    def _cleanup_gate_worktree(self, gate_path: Path) -> None:
        self._git(["worktree", "remove", "--force", str(gate_path)], check=False)
        if gate_path.exists():
            shutil.rmtree(gate_path, ignore_errors=True)
        self._git(["worktree", "prune"], check=False)

    def _reject(
        self,
        *,
        gate_run_id: str,
        submission: PatchSubmission,
        stages_passed: List[str],
        stage: str,
        error: str,
        gate_state_version: int,
        staleness_score: float,
    ) -> GateResult:
        self.event_store.append(
            actor="gate",
            kind="gate.rejected",
            project_id=self.project_id,
            task_id=submission.task_id,
            payload={
                "gate_run_id": gate_run_id,
                "patch_id": submission.patch_id,
                "candidate_commit_sha": submission.candidate_commit_sha,
                "rejection_stage": stage,
                "error": error,
                "stages_passed": stages_passed,
                "dispatch_state_version": submission.dispatch_state_version,
                "gate_state_version": gate_state_version,
            },
        )
        return GateResult(
            gate_run_id=gate_run_id,
            patch_id=submission.patch_id,
            task_id=submission.task_id,
            agent_id=submission.agent_id,
            dispatch_state_version=submission.dispatch_state_version,
            gate_state_version=gate_state_version,
            status=GateStatus.REJECTED,
            stages_passed=stages_passed,
            rejection_stage=stage,
            error_detail=error,
            staleness_score=staleness_score,
            verification_level=self.verification_level,
        )

    def evaluate_submission(
        self,
        submission: PatchSubmission,
        staleness_score: float = 0.0,
        visible_test_cmd: Optional[List[str]] = None,
        visible_test_harness: Optional[dict[str, Any]] = None,
    ) -> GateResult:
        """Verify and, on success, integrate the exact submitted candidate commit."""
        gate_run_id = f"gate_{uuid.uuid4().hex[:8]}"
        gate_state_version = self.event_store.current_version(self.project_id)
        stages_passed: List[str] = []

        self.event_store.append(
            actor="gate",
            kind="gate.started",
            project_id=self.project_id,
            task_id=submission.task_id,
            payload={
                "gate_run_id": gate_run_id,
                "patch_id": submission.patch_id,
                "candidate_commit_sha": submission.candidate_commit_sha,
                "dispatch_state_version": submission.dispatch_state_version,
                "gate_state_version": gate_state_version,
                "verification_level": self.verification_level,
            },
        )

        if staleness_score > 0.8:
            return self._reject(
                gate_run_id=gate_run_id,
                submission=submission,
                stages_passed=stages_passed,
                stage="G0_STALE",
                error=f"candidate is stale (score={staleness_score:.2f} > 0.80)",
                gate_state_version=gate_state_version,
                staleness_score=staleness_score,
            )

        try:
            self._ensure_clean_integration_tree()
        except IntegrationGateError as exc:
            return self._reject(
                gate_run_id=gate_run_id,
                submission=submission,
                stages_passed=stages_passed,
                stage="G0_DIRTY_INTEGRATION",
                error=str(exc),
                gate_state_version=gate_state_version,
                staleness_score=staleness_score,
            )

        candidate_exists = self._git(
            ["cat-file", "-e", f"{submission.candidate_commit_sha}^{{commit}}"],
            check=False,
        )
        if candidate_exists.returncode != 0:
            return self._reject(
                gate_run_id=gate_run_id,
                submission=submission,
                stages_passed=stages_passed,
                stage="G0_INVALID_CANDIDATE",
                error="candidate_commit_sha does not resolve to a git commit",
                gate_state_version=gate_state_version,
                staleness_score=staleness_score,
            )

        gate_path: Optional[Path] = None
        try:
            gate_path = self._create_gate_worktree(gate_run_id)
            apply_res = self._git(
                arc_git_write_args(
                    ["cherry-pick", submission.candidate_commit_sha],
                    user_name="ARC Gate",
                    user_email="arc-gate@local",
                ),
                cwd=gate_path,
                check=False,
                env=arc_git_write_env(),
            )
            if apply_res.returncode != 0:
                self._git(["cherry-pick", "--abort"], cwd=gate_path, check=False)
                return self._reject(
                    gate_run_id=gate_run_id,
                    submission=submission,
                    stages_passed=stages_passed,
                    stage="G0_INTEGRATION_CONFLICT",
                    error=(
                        apply_res.stderr or apply_res.stdout or "candidate cannot be applied"
                    ).strip(),
                    gate_state_version=gate_state_version,
                    staleness_score=staleness_score,
                )
            stages_passed.append("G0_candidate_applied")

            static_res = StaticVerifier(gate_path).verify_syntax()
            if not static_res.passed:
                return self._reject(
                    gate_run_id=gate_run_id,
                    submission=submission,
                    stages_passed=stages_passed,
                    stage="G1_STATIC",
                    error="; ".join(static_res.errors),
                    gate_state_version=gate_state_version,
                    staleness_score=staleness_score,
                )
            stages_passed.append("G1_static")

            harness = dict(visible_test_harness or self.visible_test_harness)
            if harness:
                test_res = AdversarialTestRunner(gate_path, harness=harness).run_tests()
                if not test_res.passed:
                    return self._reject(
                        gate_run_id=gate_run_id,
                        submission=submission,
                        stages_passed=stages_passed,
                        stage="G2_TESTS",
                        error=test_res.output[-8000:],
                        gate_state_version=gate_state_version,
                        staleness_score=staleness_score,
                    )
                stages_passed.append("G2_visible_tests")
            elif visible_test_cmd:
                test_res = AdversarialTestRunner(gate_path).run_tests(visible_test_cmd)
                if not test_res.passed:
                    return self._reject(
                        gate_run_id=gate_run_id,
                        submission=submission,
                        stages_passed=stages_passed,
                        stage="G2_TESTS",
                        error=test_res.output[-8000:],
                        gate_state_version=gate_state_version,
                        staleness_score=staleness_score,
                    )
                stages_passed.append("G2_visible_tests")
            else:
                stages_passed.append("G2_not_configured")

            if self.verification_level in ("V2", "V3"):
                review_res = self.reviewer.review_patch(submission.diff, submission.summary)
                if not review_res.passed:
                    return self._reject(
                        gate_run_id=gate_run_id,
                        submission=submission,
                        stages_passed=stages_passed,
                        stage="V2_REVIEW",
                        error="; ".join(review_res.security_violations),
                        gate_state_version=gate_state_version,
                        staleness_score=staleness_score,
                    )
                stages_passed.append("V2_reviewer")

            merge_res = self._git(
                arc_git_write_args(
                    ["cherry-pick", submission.candidate_commit_sha],
                    user_name="ARC Gate",
                    user_email="arc-gate@local",
                ),
                check=False,
                env=arc_git_write_env(),
            )
            if merge_res.returncode != 0:
                self._git(["cherry-pick", "--abort"], check=False)
                return self._reject(
                    gate_run_id=gate_run_id,
                    submission=submission,
                    stages_passed=stages_passed,
                    stage="G4_FINAL_INTEGRATION",
                    error=(
                        merge_res.stderr or merge_res.stdout or "final cherry-pick failed"
                    ).strip(),
                    gate_state_version=gate_state_version,
                    staleness_score=staleness_score,
                )

            merged_commit_sha = self._git(["rev-parse", "HEAD"]).stdout.strip()
            stages_passed.append("G4_integrated")

            # This event is the validation boundary for durable project memory.
            # Knowledge from rejected candidates is intentionally excluded.
            self.event_store.append(
                actor="gate",
                kind="gate.accepted",
                project_id=self.project_id,
                task_id=submission.task_id,
                payload={
                    "gate_run_id": gate_run_id,
                    "patch_id": submission.patch_id,
                    "candidate_commit_sha": submission.candidate_commit_sha,
                    "merged_commit_sha": merged_commit_sha,
                    "agent_id": submission.agent_id,
                    "summary": submission.summary,
                    "decisions": submission.decisions,
                    "assumptions": submission.assumptions,
                    "procedures": submission.procedures,
                    "failures": submission.failures,
                    "memories_used": submission.memories_used,
                    "stages_passed": stages_passed,
                    "staleness_score": staleness_score,
                },
            )

            return GateResult(
                gate_run_id=gate_run_id,
                patch_id=submission.patch_id,
                task_id=submission.task_id,
                agent_id=submission.agent_id,
                dispatch_state_version=submission.dispatch_state_version,
                gate_state_version=gate_state_version,
                status=GateStatus.ACCEPTED,
                stages_passed=stages_passed,
                staleness_score=staleness_score,
                verification_level=self.verification_level,
                merged_commit_sha=merged_commit_sha,
            )
        except IntegrationGateError as exc:
            return self._reject(
                gate_run_id=gate_run_id,
                submission=submission,
                stages_passed=stages_passed,
                stage="GATE_INTERNAL",
                error=str(exc),
                gate_state_version=gate_state_version,
                staleness_score=staleness_score,
            )
        finally:
            if gate_path is not None:
                self._cleanup_gate_worktree(gate_path)
