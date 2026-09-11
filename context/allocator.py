"""Context budget allocator across classes C0-C6 with risk-aware adjustments."""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ClassBudgets:
    c0_authoritative: int
    c1_decisions: int
    c2_code: int
    c3_assumptions: int
    c4_failures: int
    c5_procedures: int
    c6_episodes: int
    total_budget: int


class BudgetAllocator:
    """Allocates finite token budget across context classes based on risk and task requirements."""

    def __init__(self, base_budget: int = 24000) -> None:
        self.base_budget = base_budget

    def allocate(self, risk: float = 0.5, declared_budget: Optional[int] = None) -> ClassBudgets:
        """Compute token quotas per class according to Sections 25 & 26."""
        total = declared_budget or self.base_budget

        # Apply risk-aware multiplier (Section 26)
        if risk < 0.3:
            total = int(total * 0.70)
        elif risk > 0.7:
            total = int(total * 1.25)

        # Baseline proportions for 24k:
        # C0: 3000 (12.5%)
        # C1: 2000 (8.33%)
        # C2: 12000 (50.0%)
        # C3: 2000 (8.33%)
        # C4: 2000 (8.33%)
        # C5: 2000 (8.33%)
        # C6: 1000 (4.17%)
        ratio_c0 = 3000 / 24000
        ratio_c1 = 2000 / 24000
        ratio_c2 = 12000 / 24000
        ratio_c3 = 2000 / 24000
        ratio_c4 = 2000 / 24000
        ratio_c5 = 2000 / 24000
        ratio_c6 = 1000 / 24000

        # Adjust for high risk: allocate more to code evidence and failure recovery
        if risk > 0.7:
            ratio_c2 += 0.05
            ratio_c4 += 0.03
            ratio_c6 = max(0.01, ratio_c6 - 0.04)

        c0 = max(1000, int(total * ratio_c0))
        c1 = max(500, int(total * ratio_c1))
        c2 = max(2000, int(total * ratio_c2))
        c3 = max(500, int(total * ratio_c3))
        c4 = max(500, int(total * ratio_c4))
        c5 = max(500, int(total * ratio_c5))
        c6 = max(200, int(total * ratio_c6))

        return ClassBudgets(
            c0_authoritative=c0,
            c1_decisions=c1,
            c2_code=c2,
            c3_assumptions=c3,
            c4_failures=c4,
            c5_procedures=c5,
            c6_episodes=c6,
            total_budget=total,
        )

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count (approximately 4 characters per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)
