"""Deterministic candidate memory extraction from authoritative events."""

import uuid
from typing import List, Optional
from state.hashing import compute_hash
from state.models import Event
from memory.models import (
    Memory,
    MemoryRepresentation,
    MemoryStatus,
    MemoryType,
)


class CandidateExtractor:
    """Extracts candidate memory objects from authoritative events based on deterministic triggers."""

    @staticmethod
    def extract_from_event(event: Event) -> List[Memory]:
        candidates: List[Memory] = []

        # Trigger 1: Constraint added
        if event.kind == "project.constraint_added":
            constraint_text = event.payload.get("constraint", "")
            mem_id = f"M_CONST_{event.id}"
            candidates.append(
                Memory(
                    memory_id=mem_id,
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

        # Trigger 2: Gate rejection / Failure
        elif event.kind in ("gate.c0_failed", "gate.c1_failed", "gate.c2_failed", "gate.v2_failed", "gate.rejected"):
            reason = event.payload.get("error", event.payload.get("reason", "Gate rejection"))
            rejection_stage = event.payload.get("rejection_stage", event.kind)
            mem_id = f"M_FAIL_{event.id}"
            candidates.append(
                Memory(
                    memory_id=mem_id,
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
                    tags=["failure", rejection_stage, event.task_id or ""],
                )
            )

        # Trigger 3: Gate accepted with submitted decisions and procedures
        elif event.kind == "gate.accepted":
            task_id = event.task_id or ""
            patch_id = event.payload.get("patch_id", "")
            # Look inside payload for agent decisions / procedures recorded
            decisions = event.payload.get("decisions", [])
            for idx, dec in enumerate(decisions):
                dec_text = dec if isinstance(dec, str) else dec.get("decision", dec.get("text", str(dec)))
                mem_id = f"M_DEC_{event.id}_{idx}"
                candidates.append(
                    Memory(
                        memory_id=mem_id,
                        project_id=event.project_id,
                        type=MemoryType.DECISION,
                        representation=MemoryRepresentation.DECISION_RECORD,
                        content_json={"decision": dec_text, "task_id": task_id, "patch_id": patch_id},
                        content_text=f"Decision: {dec_text}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=1.0,
                        importance=0.90,
                        predicted_reuse=0.85,
                        token_size=len(dec_text.split()) + 12,
                        content_hash=compute_hash(dec_text),
                        producer_type="deterministic",
                        source_events=[event.id],
                        tags=["decision", task_id],
                    )
                )

            # Reusable procedure validated by gate
            if "procedure" in event.payload:
                proc = event.payload["procedure"]
                proc_text = proc if isinstance(proc, str) else proc.get("rule", str(proc))
                mem_id = f"M_PROC_{event.id}"
                candidates.append(
                    Memory(
                        memory_id=mem_id,
                        project_id=event.project_id,
                        type=MemoryType.PROCEDURE,
                        representation=MemoryRepresentation.PROCEDURE,
                        content_json={"procedure": proc_text, "task_id": task_id},
                        content_text=f"Procedure: {proc_text}",
                        created_event=event.id,
                        valid_from_event=event.id,
                        state_version_at_write=event.id,
                        status=MemoryStatus.ACTIVE,
                        confidence=1.0,
                        importance=0.80,
                        predicted_reuse=0.85,
                        token_size=len(proc_text.split()) + 10,
                        content_hash=compute_hash(proc_text),
                        producer_type="deterministic",
                        source_events=[event.id],
                        tags=["procedure", task_id],
                    )
                )

        # Trigger 4: Task merged / completed summary
        elif event.kind in ("task.merged", "task.completed"):
            task_id = event.task_id or ""
            summary_text = event.payload.get("summary", f"Task {task_id} merged successfully")
            mem_id = f"M_TSUM_{event.id}"
            candidates.append(
                Memory(
                    memory_id=mem_id,
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
                    token_size=len(summary_text.split()) + 15,
                    content_hash=compute_hash(summary_text),
                    producer_type="deterministic",
                    source_events=[event.id],
                    tags=["summary", task_id],
                )
            )

        return candidates
