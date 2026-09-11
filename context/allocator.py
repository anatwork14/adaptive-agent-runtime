"""Context budget allocator across classes C0-C6."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ClassBudgets:
    c0_authoritative: int
    c1_decisions: int
    c2_code: int
    c3_assumptions: int
    c4_failures: int
    c5_procedures: int
    c6_episodes: int
    total_budget: int

    @property
    def allocated_total(self) -> int:
        return (
            self.c0_authoritative
            + self.c1_decisions
            + self.c2_code
            + self.c3_assumptions
            + self.c4_failures
            + self.c5_procedures
            + self.c6_episodes
        )


class BudgetAllocator:
    """Allocate a hard token ceiling across context classes.

    Risk changes the *distribution* of a declared budget; it never silently
    expands the budget. This is important for iso-token / iso-cost evaluation.
    """

    def __init__(self, base_budget: int = 24000) -> None:
        self.base_budget = base_budget

    def allocate(
        self,
        risk: float = 0.5,
        declared_budget: Optional[int] = None,
    ) -> ClassBudgets:
        total = int(declared_budget or self.base_budget)
        if total <= 0:
            raise ValueError("context token budget must be positive")

        # Baseline proportions. For low risk we reduce historical/assumption
        # context and bias toward the authoritative core + code. For high risk
        # we allocate more to code/failure evidence. We then normalize exactly
        # to one hard budget.
        weights = {
            "c0": 0.125,
            "c1": 0.0833,
            "c2": 0.5000,
            "c3": 0.0833,
            "c4": 0.0833,
            "c5": 0.0833,
            "c6": 0.0418,
        }
        if risk < 0.3:
            weights["c0"] += 0.03
            weights["c2"] += 0.05
            weights["c3"] -= 0.02
            weights["c4"] -= 0.02
            weights["c6"] -= 0.04
        elif risk > 0.7:
            weights["c2"] += 0.05
            weights["c4"] += 0.04
            weights["c6"] -= 0.03
            weights["c1"] -= 0.02
            weights["c3"] -= 0.02
            weights["c5"] -= 0.02

        weights = {key: max(0.0, value) for key, value in weights.items()}
        weight_sum = sum(weights.values())
        normalized = {key: value / weight_sum for key, value in weights.items()}

        raw = {key: int(total * value) for key, value in normalized.items()}
        # Integer rounding leaves a few tokens. Give them to code evidence, the
        # highest-value expandable class.
        raw["c2"] += total - sum(raw.values())

        result = ClassBudgets(
            c0_authoritative=raw["c0"],
            c1_decisions=raw["c1"],
            c2_code=raw["c2"],
            c3_assumptions=raw["c3"],
            c4_failures=raw["c4"],
            c5_procedures=raw["c5"],
            c6_episodes=raw["c6"],
            total_budget=total,
        )
        if result.allocated_total != total:
            raise AssertionError("context class allocation must equal total budget")
        return result

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Cheap deterministic estimate (~4 UTF-8 characters/token)."""
        if not text:
            return 0
        return max(1, (len(text) + 3) // 4)
