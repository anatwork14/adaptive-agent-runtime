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

    @staticmethod
    def _semantically_eligible(
        profile: AgentProfile,
        *,
        required: set[str],
        task_type: str,
    ) -> bool:
        if not profile.enabled or profile.provider in {"mock", "openrouter"}:
            return False
        caps = {item.lower() for item in profile.capabilities}
        if required:
            return required.issubset(caps)
        role = profile.role.lower()
        return (
            task_type in caps
            or role == task_type
            or role in {"implementation", "general", "worker"}
        )

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
        profiles = list(profiles)
        candidates: list[tuple[AgentProfile, RouteDecision]] = []
        required = {item.lower() for item in task.required_capabilities}
        task_type = task.task_type.lower()
        capable_real_profiles = [
            profile
            for profile in profiles
            if self._semantically_eligible(profile, required=required, task_type=task_type)
        ]

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
                (
                    profile,
                    RouteDecision(
                        task_id=task.task_id,
                        agent_name=profile.name,
                        score=round(score, 4),
                        policy=self.policy,
                        reasons=tuple(reasons),
                    ),
                )
            )

        real = [item for item in candidates if item[0].provider != "mock"]
        if real:
            return sorted(real, key=lambda item: (-item[1].score, item[1].agent_name))[0][1]

        # If the project has a real agent that is semantically capable but is
        # signed out, missing, disabled by load, or otherwise unavailable, fail
        # closed instead of making a fake-looking smoke edit with MockAgent.
        if capable_real_profiles:
            states = []
            for profile in capable_real_profiles:
                readiness = doctor.get(profile.name)
                active = int(active_counts.get(profile.name, 0))
                if active >= profile.max_concurrency:
                    state = f"SATURATED {active}/{profile.max_concurrency}"
                else:
                    state = readiness.status if readiness else "UNKNOWN"
                states.append(f"{profile.name}={state}")
            raise RuntimeError(
                f"Real agents are configured for task {task.task_id} but none are currently routable: "
                + ", ".join(states)
            )

        mock_candidates = [item for item in candidates if item[0].provider == "mock"]
        if mock_candidates:
            profile, decision = sorted(
                mock_candidates,
                key=lambda item: (-item[1].score, item[1].agent_name),
            )[0]
            del profile
            return RouteDecision(
                task_id=decision.task_id,
                agent_name=decision.agent_name,
                score=decision.score,
                policy=decision.policy,
                reasons=decision.reasons + (
                    "mock fallback: no capable real agent profile is configured",
                ),
            )

        raise RuntimeError(
            f"No READY agent satisfies task {task.task_id} "
            f"(type={task.task_type}, required={sorted(required)})"
        )
