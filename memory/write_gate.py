"""Memory Write Gate enforcing scoring heuristics before persistence."""

from dataclasses import dataclass
from typing import Optional
from memory.models import Memory, MemoryType


@dataclass
class WriteScoreBreakdown:
    total_score: float
    passed: bool
    durable_decision: float
    dependency_reach: float
    failure_recurrence_risk: float
    expected_reuse: float
    novelty: float
    source_confidence: float
    redundancy: float
    storage_cost: float


class MemoryWriteGate:
    """Evaluates whether candidate memories meet quality and utility thresholds for retention."""

    def __init__(self, write_threshold: float = 2.0) -> None:
        self.write_threshold = write_threshold

    def evaluate(
        self,
        candidate: Memory,
        novelty: float = 1.0,
        redundancy: float = 0.0,
        dependency_reach: float = 0.5,
    ) -> WriteScoreBreakdown:
        """Score candidate memory according to specification formula."""
        # Durable decision flag
        durable_decision = 1.0 if candidate.type in (MemoryType.DECISION, MemoryType.CONSTRAINT) else 0.0
        
        # Failure recurrence risk
        failure_risk = 1.0 if candidate.type == MemoryType.FAILURE else 0.0

        # Expected reuse from memory metadata
        expected_reuse = candidate.predicted_reuse
        source_confidence = candidate.confidence

        # Approximate storage cost based on token size
        storage_cost = min(1.0, candidate.token_size / 2000.0) if candidate.token_size else 0.1

        total_score = (
            2.0 * durable_decision
            + 1.5 * dependency_reach
            + 1.5 * failure_risk
            + 1.2 * expected_reuse
            + 1.0 * novelty
            + 0.8 * source_confidence
            - 1.2 * redundancy
            - 0.5 * storage_cost
        )

        passed = total_score >= self.write_threshold
        return WriteScoreBreakdown(
            total_score=round(total_score, 4),
            passed=passed,
            durable_decision=durable_decision,
            dependency_reach=dependency_reach,
            failure_recurrence_risk=failure_risk,
            expected_reuse=expected_reuse,
            novelty=novelty,
            source_confidence=source_confidence,
            redundancy=redundancy,
            storage_cost=storage_cost,
        )
