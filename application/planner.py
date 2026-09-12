"""Deterministic objective decomposition for ARC v0.5.

This module intentionally provides a reproducible baseline planner. Model-driven
planning can later implement the same MissionPlan contract and be evaluated
against it rather than becoming an unmeasurable hidden dependency.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List

from pydantic import BaseModel, Field


class PlanTask(BaseModel):
    key: str
    goal: str
    task_type: str = "implementation"
    dependencies: List[str] = Field(default_factory=list)
    files: List[str] = Field(default_factory=list)
    acceptance: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    risk: float = 0.5
    token_budget: int = 24000


class MissionPlan(BaseModel):
    objective: str
    planner: str = "deterministic-v1"
    tasks: List[PlanTask] = Field(default_factory=list)


def _kind(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    parts = {part.lower() for part in PurePosixPath(path).parts}
    if name.startswith("test_") or name.endswith("_test.py") or "tests" in parts or "test" in parts:
        return "test"
    if name.endswith((".md", ".rst", ".txt")) or "docs" in parts:
        return "docs"
    return "implementation"


def _group_key(path: str) -> str:
    parts = PurePosixPath(path).parts
    if len(parts) <= 1:
        return "root"
    return parts[0]


class DeterministicPlanner:
    """Decompose an objective using declared repository surfaces.

    Source work is split by top-level module, docs are isolated, and tests wait
    for implementation work. When no files are supplied, the objective remains
    one implementation task. This is intentionally simple but fully replayable.
    """

    name = "deterministic-v1"

    def plan(
        self,
        objective: str,
        *,
        files: List[str] | None = None,
        acceptance: List[str] | None = None,
        risk: float = 0.5,
        token_budget: int = 24000,
        max_tasks: int = 8,
    ) -> MissionPlan:
        objective = objective.strip()
        if not objective:
            raise ValueError("Mission objective cannot be empty")
        files = list(dict.fromkeys(files or []))
        acceptance = acceptance or []
        if max_tasks < 1:
            raise ValueError("max_tasks must be >= 1")

        if not files:
            return MissionPlan(
                objective=objective,
                planner=self.name,
                tasks=[
                    PlanTask(
                        key="implementation",
                        goal=objective,
                        task_type="implementation",
                        acceptance=acceptance,
                        required_capabilities=["implementation"],
                        risk=risk,
                        token_budget=token_budget,
                    )
                ],
            )

        source_groups: dict[str, list[str]] = {}
        docs: list[str] = []
        tests: list[str] = []
        for path in files:
            kind = _kind(path)
            if kind == "test":
                tests.append(path)
            elif kind == "docs":
                docs.append(path)
            else:
                source_groups.setdefault(_group_key(path), []).append(path)

        tasks: list[PlanTask] = []
        source_keys: list[str] = []
        for index, (group, group_files) in enumerate(sorted(source_groups.items()), start=1):
            key = f"impl-{index}"
            source_keys.append(key)
            tasks.append(
                PlanTask(
                    key=key,
                    goal=f"{objective} — implement {group} surface",
                    task_type="implementation",
                    files=group_files,
                    acceptance=acceptance,
                    required_capabilities=["implementation"],
                    risk=risk,
                    token_budget=token_budget,
                )
            )

        if docs:
            tasks.append(
                PlanTask(
                    key="docs",
                    goal=f"{objective} — update documentation",
                    task_type="docs",
                    dependencies=list(source_keys),
                    files=docs,
                    acceptance=acceptance,
                    required_capabilities=["docs"],
                    risk=max(0.1, risk - 0.15),
                    token_budget=token_budget,
                )
            )

        if tests:
            tasks.append(
                PlanTask(
                    key="tests",
                    goal=f"{objective} — implement and validate tests",
                    task_type="test",
                    dependencies=list(source_keys),
                    files=tests,
                    acceptance=acceptance,
                    required_capabilities=["test"],
                    risk=min(1.0, risk + 0.1),
                    token_budget=token_budget,
                )
            )

        if not tasks:
            tasks.append(
                PlanTask(
                    key="implementation",
                    goal=objective,
                    task_type="implementation",
                    files=files,
                    acceptance=acceptance,
                    required_capabilities=["implementation"],
                    risk=risk,
                    token_budget=token_budget,
                )
            )

        if len(tasks) > max_tasks:
            # Deterministic compaction: keep the first max_tasks-1 tasks and
            # combine the remaining surfaces into one tail task.
            head = tasks[: max_tasks - 1]
            tail = tasks[max_tasks - 1 :]
            merged_files = [path for task in tail for path in task.files]
            merged_deps = sorted({dep for task in tail for dep in task.dependencies})
            head.append(
                PlanTask(
                    key="tail",
                    goal=f"{objective} — complete remaining planned surfaces",
                    task_type="implementation",
                    dependencies=merged_deps,
                    files=merged_files,
                    acceptance=acceptance,
                    required_capabilities=["implementation"],
                    risk=risk,
                    token_budget=token_budget,
                )
            )
            tasks = head

        return MissionPlan(objective=objective, planner=self.name, tasks=tasks)
