import pytest

from application.agents import AgentDoctorResult
from application.config import AgentProfile
from application.planner import DeterministicPlanner
from application.routing import AgentRouter
from state.models import TaskState, TaskStatus


def _doctor(name: str, status: str = "READY", provider: str = "mock") -> AgentDoctorResult:
    return AgentDoctorResult(
        name=name,
        provider=provider,
        model=None,
        executable=None,
        installed=status != "MISSING",
        status=status,
        detail="test",
    )


def test_router_prefers_required_capability_and_quality() -> None:
    task = TaskState(
        task_id="T001",
        project_id="p",
        goal="write tests",
        task_type="test",
        required_capabilities=["test"],
        status=TaskStatus.READY,
    )
    builder = AgentProfile(
        name="builder",
        provider="mock",
        role="implementation",
        capabilities=["implementation", "test"],
        quality_weight=1.0,
        cost_weight=1.0,
    )
    specialist = AgentProfile(
        name="tester",
        provider="mock",
        role="test",
        capabilities=["test"],
        quality_weight=1.3,
        cost_weight=1.0,
    )
    decision = AgentRouter("balanced").route(
        task,
        [builder, specialist],
        {"builder": _doctor("builder"), "tester": _doctor("tester")},
    )
    assert decision.agent_name == "tester"
    assert "required capabilities matched" in decision.reasons


def test_router_filters_unready_and_concurrency_saturated_mock_profiles() -> None:
    task = TaskState(
        task_id="T001",
        project_id="p",
        goal="implement",
        task_type="implementation",
        required_capabilities=["implementation"],
        status=TaskStatus.READY,
    )
    unavailable = AgentProfile(
        name="unavailable",
        provider="mock",
        capabilities=["implementation"],
    )
    busy = AgentProfile(
        name="busy",
        provider="mock",
        capabilities=["implementation"],
        max_concurrency=1,
    )
    fallback = AgentProfile(
        name="fallback",
        provider="mock",
        capabilities=["implementation"],
        max_concurrency=2,
    )
    decision = AgentRouter().route(
        task,
        [unavailable, busy, fallback],
        {
            "unavailable": _doctor("unavailable", "AUTH_REQUIRED"),
            "busy": _doctor("busy"),
            "fallback": _doctor("fallback"),
        },
        {"busy": 1},
    )
    assert decision.agent_name == "fallback"


def test_router_does_not_mask_real_auth_failure_with_mock() -> None:
    task = TaskState(
        task_id="T001",
        project_id="p",
        goal="implement",
        task_type="implementation",
        required_capabilities=["implementation"],
        status=TaskStatus.READY,
    )
    codex = AgentProfile(
        name="builder",
        provider="codex",
        capabilities=["implementation"],
    )
    mock = AgentProfile(
        name="mock",
        provider="mock",
        capabilities=["implementation"],
    )
    with pytest.raises(RuntimeError, match="builder=AUTH_REQUIRED"):
        AgentRouter().route(
            task,
            [codex, mock],
            {
                "builder": _doctor("builder", "AUTH_REQUIRED", "codex"),
                "mock": _doctor("mock"),
            },
        )


def test_router_uses_mock_when_no_capable_real_profile_is_configured() -> None:
    task = TaskState(
        task_id="T001",
        project_id="p",
        goal="write docs",
        task_type="docs",
        required_capabilities=["docs"],
        status=TaskStatus.READY,
    )
    codex = AgentProfile(
        name="builder",
        provider="codex",
        capabilities=["implementation", "test"],
    )
    mock = AgentProfile(
        name="mock",
        provider="mock",
        capabilities=["docs"],
    )
    decision = AgentRouter().route(
        task,
        [codex, mock],
        {
            "builder": _doctor("builder", "READY", "codex"),
            "mock": _doctor("mock"),
        },
    )
    assert decision.agent_name == "mock"
    assert any("no capable real agent" in reason for reason in decision.reasons)


def test_deterministic_planner_splits_source_docs_and_tests() -> None:
    plan = DeterministicPlanner().plan(
        "add auth",
        files=["src/auth.py", "docs/auth.md", "tests/test_auth.py"],
        acceptance=["tests pass"],
    )
    assert [task.task_type for task in plan.tasks] == ["implementation", "docs", "test"]
    impl = plan.tasks[0]
    docs = plan.tasks[1]
    tests = plan.tasks[2]
    assert docs.dependencies == [impl.key]
    assert tests.dependencies == [impl.key]
    assert tests.required_capabilities == ["test"]


def test_compacted_plan_has_no_dangling_dependencies() -> None:
    plan = DeterministicPlanner().plan(
        "large change",
        files=[
            "api/a.py",
            "core/b.py",
            "runtime/c.py",
            "web/d.py",
            "docs/guide.md",
            "tests/test_all.py",
        ],
        max_tasks=3,
    )
    assert len(plan.tasks) == 3
    surviving = {task.key for task in plan.tasks}
    for task in plan.tasks:
        assert set(task.dependencies).issubset(surviving)
        assert task.key not in task.dependencies
    assert plan.tasks[-1].key == "tail"


def test_single_task_compaction_is_dependency_free() -> None:
    plan = DeterministicPlanner().plan(
        "large change",
        files=["api/a.py", "core/b.py", "tests/test_all.py"],
        max_tasks=1,
    )
    assert len(plan.tasks) == 1
    assert plan.tasks[0].key == "tail"
    assert plan.tasks[0].dependencies == []
