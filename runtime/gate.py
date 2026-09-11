"""Serialized Integration Gate (G0-G3 / V0-V3)."""

import uuid
from pathlib import Path
from typing import Dict, List, Optional

from state.events import EventStore
from state.models import GateResult, GateStatus, PatchSubmission
from verification.adversarial_tests import AdversarialTestRunner
from verification.reviewer import CodeReviewer
from verification.static import StaticVerifier


class IntegrationGate:
    """Serializes integration of accepted patches through tiered validation gates."""

    def __init__(
        self,
        event_store: EventStore,
        project_id: str,
        workspace_path: str | Path,
        verification_level: str = "V0",
    ) -> None:
        self.event_store = event_store
        self.project_id = project_id
        self.workspace_path = Path(workspace_path).resolve()
        self.verification_level = verification_level
        self.static_verifier = StaticVerifier(self.workspace_path)
        self.reviewer = CodeReviewer()
        self.adversarial_runner = AdversarialTestRunner(self.workspace_path)

    def evaluate_submission(
        self,
        submission: PatchSubmission,
        staleness_score: float = 0.0,
        visible_test_cmd: Optional[List[str]] = None,
    ) -> GateResult:
        """Run serialized integration gate on agent patch submission."""
        gate_run_id = f"gate_{uuid.uuid4().hex[:8]}"
        gate_state_version = self.event_store.current_version(self.project_id)
        stages_passed: List[str] = []

        # Emit gate.started
        self.event_store.append(
            actor="gate",
            kind="gate.started",
            project_id=self.project_id,
            task_id=submission.task_id,
            payload={
                "gate_run_id": gate_run_id,
                "patch_id": submission.patch_id,
                "dispatch_state_version": submission.dispatch_state_version,
                "gate_state_version": gate_state_version,
                "verification_level": self.verification_level,
            },
        )

        # G0: Rebase / Staleness check
        # If staleness score > 0.8, reject as stale
        if staleness_score > 0.8:
            error_msg = f"G0 Failed: Patch is stale (staleness score {staleness_score:.2f} > 0.80)"
            self.event_store.append(
                actor="gate",
                kind="gate.c0_failed",
                project_id=self.project_id,
                task_id=submission.task_id,
                payload={"error": error_msg, "gate_run_id": gate_run_id},
            )
            self._emit_rejected(gate_run_id, submission, stages_passed, "G0", error_msg, gate_state_version)
            return GateResult(
                gate_run_id=gate_run_id,
                patch_id=submission.patch_id,
                task_id=submission.task_id,
                agent_id=submission.agent_id,
                dispatch_state_version=submission.dispatch_state_version,
                gate_state_version=gate_state_version,
                status=GateStatus.REJECTED,
                stages_passed=stages_passed,
                rejection_stage="G0",
                error_detail=error_msg,
                staleness_score=staleness_score,
                verification_level=self.verification_level,
            )
        stages_passed.append("G0_rebase")

        # G1: Syntax & Build check
        syntax_res = self.static_verifier.verify_syntax()
        if not syntax_res.passed:
            error_msg = f"G1 Failed: Syntax errors: {'; '.join(syntax_res.errors)}"
            self.event_store.append(
                actor="gate",
                kind="gate.c1_failed",
                project_id=self.project_id,
                task_id=submission.task_id,
                payload={"error": error_msg, "gate_run_id": gate_run_id},
            )
            self._emit_rejected(gate_run_id, submission, stages_passed, "G1", error_msg, gate_state_version)
            return GateResult(
                gate_run_id=gate_run_id,
                patch_id=submission.patch_id,
                task_id=submission.task_id,
                agent_id=submission.agent_id,
                dispatch_state_version=submission.dispatch_state_version,
                gate_state_version=gate_state_version,
                status=GateStatus.REJECTED,
                stages_passed=stages_passed,
                rejection_stage="G1",
                error_detail=error_msg,
                staleness_score=staleness_score,
                verification_level=self.verification_level,
            )
        stages_passed.append("G1_build_syntax")

        # G2: Visible tests
        if visible_test_cmd:
            test_res = self.adversarial_runner.run_tests(visible_test_cmd)
            if not test_res.passed:
                error_msg = f"G2 Failed: Visible tests failed:\n{test_res.output}"
                self.event_store.append(
                    actor="gate",
                    kind="gate.c2_failed",
                    project_id=self.project_id,
                    task_id=submission.task_id,
                    payload={"error": error_msg, "gate_run_id": gate_run_id},
                )
                self._emit_rejected(gate_run_id, submission, stages_passed, "G2", error_msg, gate_state_version)
                return GateResult(
                    gate_run_id=gate_run_id,
                    patch_id=submission.patch_id,
                    task_id=submission.task_id,
                    agent_id=submission.agent_id,
                    dispatch_state_version=submission.dispatch_state_version,
                    gate_state_version=gate_state_version,
                    status=GateStatus.REJECTED,
                    stages_passed=stages_passed,
                    rejection_stage="G2",
                    error_detail=error_msg,
                    staleness_score=staleness_score,
                    verification_level=self.verification_level,
                )
        stages_passed.append("G2_visible_tests")

        # G3: Tiered verification (V0, V1, V2, V3)
        if self.verification_level in ("V2", "V3"):
            review_res = self.reviewer.review_patch(submission.diff, submission.summary)
            if not review_res.passed:
                error_msg = f"V2 Failed: Reviewer security check failed: {'; '.join(review_res.security_violations)}"
                self.event_store.append(
                    actor="gate",
                    kind="gate.v2_failed",
                    project_id=self.project_id,
                    task_id=submission.task_id,
                    payload={"error": error_msg, "gate_run_id": gate_run_id},
                )
                self._emit_rejected(gate_run_id, submission, stages_passed, "V2", error_msg, gate_state_version)
                return GateResult(
                    gate_run_id=gate_run_id,
                    patch_id=submission.patch_id,
                    task_id=submission.task_id,
                    agent_id=submission.agent_id,
                    dispatch_state_version=submission.dispatch_state_version,
                    gate_state_version=gate_state_version,
                    status=GateStatus.REJECTED,
                    stages_passed=stages_passed,
                    rejection_stage="V2",
                    error_detail=error_msg,
                    staleness_score=staleness_score,
                    verification_level=self.verification_level,
                )
            stages_passed.append("V2_reviewer")

        # All gates passed: emit gate.accepted
        self.event_store.append(
            actor="gate",
            kind="gate.accepted",
            project_id=self.project_id,
            task_id=submission.task_id,
            payload={
                "gate_run_id": gate_run_id,
                "patch_id": submission.patch_id,
                "agent_id": submission.agent_id,
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
        )

    def _emit_rejected(
        self,
        gate_run_id: str,
        submission: PatchSubmission,
        stages_passed: List[str],
        rejection_stage: str,
        error_detail: str,
        gate_state_version: int,
    ) -> None:
        self.event_store.append(
            actor="gate",
            kind="gate.rejected",
            project_id=self.project_id,
            task_id=submission.task_id,
            payload={
                "gate_run_id": gate_run_id,
                "patch_id": submission.patch_id,
                "rejection_stage": rejection_stage,
                "error": error_detail,
                "stages_passed": stages_passed,
                "dispatch_state_version": submission.dispatch_state_version,
                "gate_state_version": gate_state_version,
            },
        )
