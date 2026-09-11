"""Deterministic candidate memory extraction from authoritative events."""

from typing import List

from memory.models import Memory, MemoryRepresentation, MemoryStatus, MemoryType
from state.hashing import compute_hash
from state.models import Event


class CandidateExtractor:
    """Extract typed candidate memories from committed authoritative events."""

    @staticmethod
    def extract_from_event(event: Event) -> List[Memory]:
        candidates: List[Memory] = []

        if event.kind == "project.constraint_added":
            constraint_text = event.payload.get("constraint", "")
            candidates.append(
                Memory(
                    memory_id=f"M_CONST_{event.id}",
                    project_id=event.project_id,
                    type=MemoryType.CONSTRAINT,
                    representation=MemoryRepresentation.STRUCTURED_FACT,
                    content_json={"constraint": constraint_text},
                    content_text=f"Project Constraint: {constraint_text}",
                    created_event=event.id,
                    valid_from_event=event.id,
                    state_version_at_write=event.id,
                    status=MemoryStatus.ACTIVE,
                    confidence=1.0,
                    importance=0.95,
                    predicted_reuse=0.95,
                    token_size=len(constraint_text.split()) + 10,
                    content_hash=compute_hash(constraint_text),
                    producer_type="deterministic",
                    source_events=[event.id],
                    tags=["constraint", "rule"],
                )
            )

        elif event.kind in (
            "gate.c0_failed",
            "gate.c1_failed",
            "gate.c2_failed",
            "gate.v2_failed",
            "gate.rejected",
        ):
            reason = event.payload.get("error", event.payload.get("reason", "Gate rejection"))
            rejection_stage = event.payload.get("rejection_stage", event.kind)
            candidates.append(
                Memory(
                    memory_id=f"M_FAIL_{event.id}",
                    project_id=event.project_id,
                    type=MemoryType.FAILURE,
                    representation=MemoryRepresentation.SUMMARY,
                    content_json={
                        "stage": rejection_stage,
                        "error": reason,
                        "task_id": event.task_id,
                    },
                    content_text=f"Failure at {rejection_stage}: {reason}",
                    created_event=event.id,
                    valid_from_event=event.id,
                    state_version_at_write=event.id,
                    status=MemoryStatus.ACTIVE,
                    confidence=1.0,
                    importance=0.85,
                    predicted_reuse=0.80,
                    token_size=len(str(reason).split()) + 15,
                    content_hash=compute_hash(str(reason)),
                    producer_type="deterministic",
                    source_events=[event.id],
                    tags=["failure", str(rejection_stage), event.task_id or ""],
                )
            )

        elif event.kind == "gate.accepted":
            # Only knowledge attached to an accepted candidate is eligible for
            # durable project memory. Submitted-but-rejected reasoning never
            # crosses this boundary.
            task_id = event.task_id or ""
            patch_id = event.payload.get("patch_id", "")

            for idx, decision in enumerate(event.payload.get("decisions", [])):
                if isinstance(decision, str):
                    text = decision
                    raw = {"decision": decision}
                else:
                    raw = dict(decision)
                    text = raw.get("decision", raw.get("text", str(raw)))
                candidates.append(
                    Memory(
                        memory_id=f"M_DEC_{event.id}_{idx}",
                        project_id=event.project_id,
                        type=MemoryType.DECISION,
                        representation=MemoryRepresentation.DECISION_RECORD,
                        content_json={**raw, "task_id": task_id, "patch_id": patch_id},
                        content_text=f"Decision: {text}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=float(raw.get("confidence", 1.0)),
                        importance=float(raw.get("importance", 0.90)),
                        predicted_reuse=float(raw.get("predicted_reuse", 0.85)),
                        token_size=len(str(text).split()) + 12,
                        content_hash=compute_hash(str(text)),
                        producer_type=str(raw.get("producer_type", "agent")),
                        source_events=[event.id],
                        tags=["decision", task_id],
                    )
                )

            for idx, assumption in enumerate(event.payload.get("assumptions", [])):
                if isinstance(assumption, str):
                    text = assumption
                    raw = {"text": assumption}
                else:
                    raw = dict(assumption)
                    text = raw.get("text", raw.get("assumption", str(raw)))
                candidates.append(
                    Memory(
                        memory_id=f"M_ASSUMP_{event.id}_{idx}",
                        project_id=event.project_id,
                        type=MemoryType.ASSUMPTION,
                        representation=MemoryRepresentation.STRUCTURED_FACT,
                        content_json={**raw, "task_id": task_id, "patch_id": patch_id},
                        content_text=f"Assumption: {text}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=float(raw.get("confidence", 0.7)),
                        importance=float(raw.get("importance", 0.65)),
                        predicted_reuse=float(raw.get("predicted_reuse", 0.60)),
                        token_size=len(str(text).split()) + 12,
                        content_hash=compute_hash(str(text)),
                        producer_type=str(raw.get("producer_type", "agent")),
                        source_events=[event.id],
                        tags=["assumption", task_id],
                    )
                )

            procedures = list(event.payload.get("procedures", []))
            if "procedure" in event.payload:
                procedures.append(event.payload["procedure"])
            for idx, procedure in enumerate(procedures):
                if isinstance(procedure, str):
                    text = procedure
                    raw = {"rule": procedure}
                else:
                    raw = dict(procedure)
                    text = raw.get("rule", raw.get("text", str(raw)))
                candidates.append(
                    Memory(
                        memory_id=f"M_PROC_{event.id}_{idx}",
                        project_id=event.project_id,
                        type=MemoryType.PROCEDURE,
                        representation=MemoryRepresentation.PROCEDURE,
                        content_json={**raw, "task_id": task_id, "patch_id": patch_id},
                        content_text=f"Procedure: {text}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=float(raw.get("confidence", 1.0)),
                        importance=float(raw.get("importance", 0.80)),
                        predicted_reuse=float(raw.get("predicted_reuse", 0.85)),
                        token_size=len(str(text).split()) + 10,
                        content_hash=compute_hash(str(text)),
                        producer_type=str(raw.get("producer_type", "agent")),
                        source_events=[event.id],
                        tags=["procedure", task_id],
                    )
                )

            summary = event.payload.get("summary")
            if summary:
                candidates.append(
                    Memory(
                        memory_id=f"M_TSUM_{event.id}",
                        project_id=event.project_id,
                        type=MemoryType.TASK_SUMMARY,
                        representation=MemoryRepresentation.SUMMARY,
                        content_json={
                            "task_id": task_id,
                            "patch_id": patch_id,
                            "summary": summary,
                        },
                        content_text=f"Task Summary [{task_id}]: {summary}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=1.0,
                        importance=0.70,
                        predicted_reuse=0.60,
                        token_size=len(str(summary).split()) + 15,
                        content_hash=compute_hash(str(summary)),
                        producer_type="agent",
                        source_events=[event.id],
                        tags=["summary", task_id],
                    )
                )

        elif event.kind in ("task.merged", "task.completed"):
            task_id = event.task_id or ""
            summary_text = event.payload.get(
                "summary", f"Task {task_id} merged successfully"
            )
            candidates.append(
                Memory(
                    memory_id=f"M_TSUM_{event.id}",
                    project_id=event.project_id,
                    type=MemoryType.TASK_SUMMARY,
                    representation=MemoryRepresentation.SUMMARY,
                    content_json={"task_id": task_id, "summary": summary_text},
                    content_text=f"Task Summary [{task_id}]: {summary_text}",
                    created_event=event.id,
                    valid_from_event=event.id,
                    state_version_at_write=event.id,
                    status=MemoryStatus.ACTIVE,
                    confidence=1.0,
                    importance=0.70,
                    predicted_reuse=0.60,
                    token_size=len(str(summary_text).split()) + 15,
                    content_hash=compute_hash(str(summary_text)),
                    producer_type="deterministic",
                    source_events=[event.id],
                    tags=["summary", task_id],
                )
            )

        return candidates
