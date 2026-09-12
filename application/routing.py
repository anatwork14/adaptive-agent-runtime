"""Deterministic capability/cost/load-aware routing for ARC orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from application.agents import AgentDoctorResult
from application.config import AgentProfile
from state.models import TaskState


@dataclass(frozen=True)
class RouteDecision:
    """Explainable routing result recorded by the orchestration engine."""

    task_id: str
    agent_name: str
    score: float
    policy: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


class AgentRouter:
    """Score READY agents without hiding policy decisions inside prompts.

    The router is intentionally deterministic. Learned routing can later replace
    this policy while keeping the same RouteDecision/event contract.
    """

    def __init__(self, policy: str = "balanced") -> None:
        if policy not in {"balanced", "quality", "cost"}:
            raise ValueError("routing policy must be balanced, quality, or cost")
        self.policy = policy

    def route(
        self,
        task: TaskState,
        profiles: Iterable[AgentProfile],
        doctor: Mapping[str, AgentDoctorResult],
        active_counts: Mapping[str, int] | None = None,
        *,
        default_agent: str | None = None,
    ) -> RouteDecision:
        active_counts = active_counts or {}
        candidates: list[RouteDecision] = []
        required = {item.lower() for item in task.required_capabilities}
        task_type = task.task_type.lower()

        for profile in profiles:
            readiness = doctor.get(profile.name)
            if not profile.enabled or readiness is None or readiness.status != "READY":
                continue
            active = int(active_counts.get(profile.name, 0))
            if active >= profile.max_concurrency:
                continue

            caps = {item.lower() for item in profile.capabilities}
            reasons: list[str] = []
            score = 0.0

            missing = required.difference(caps)
            if required and missing:
                # Required capabilities are a hard constraint.
                continue
            if required:
                score += 4.0 * len(required)
                reasons.append("required capabilities matched")

            if task_type in caps:
                score += 3.0
                reasons.append(f"task type {task_type} matched")
            if profile.role.lower() == task_type:
                score += 2.0
                reasons.append("role matched task type")
            elif profile.role.lower() in {"implementation", "general", "worker"}:
                score += 0.5

            if self.policy == "quality":
                score += 3.0 * profile.quality_weight - 0.5 * profile.cost_weight
            elif self.policy == "cost":
                score += 1.0 * profile.quality_weight - 3.0 * profile.cost_weight
            else:
                score += 2.0 * profile.quality_weight - 1.5 * profile.cost_weight

            load_ratio = active / max(profile.max_concurrency, 1)
            score -= 2.5 * load_ratio
            if active:
                reasons.append(f"load penalty {active}/{profile.max_concurrency}")

            if default_agent and profile.name == default_agent:
                score += 0.1
                reasons.append("default-agent tie breaker")

            candidates.append(
                RouteDecision(
                    task_id=task.task_id,
                    agent_name=profile.name,
                    score=round(score, 4),
                    policy=self.policy,
                    reasons=tuple(reasons),
                )
            )

        if not candidates:
            raise RuntimeError(
                f"No READY agent satisfies task {task.task_id} "
                f"(type={task.task_type}, required={sorted(required)})"
            )
        return sorted(candidates, key=lambda item: (-item.score, item.agent_name))[0]
