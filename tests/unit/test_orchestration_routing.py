from application.agents import AgentDoctorResult
from application.config import AgentProfile
from application.planner import DeterministicPlanner
from application.routing import AgentRouter
from state.models import TaskState, TaskStatus


def _doctor(name: str, status: str = "READY") -> AgentDoctorResult:
    return AgentDoctorResult(
        name=name,
        provider="mock",
        model=None,
        executable=None,
        installed=True,
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


def test_router_filters_unready_and_concurrency_saturated_profiles() -> None:
    task = TaskState(
        task_id="T001",
        project_id="p",
        goal="implement",
        task_type="implementation",
        required_capabilities=["implementation"],
        status=TaskStatus.READY,
    )
    unavailable = AgentProfile(
        name="codex",
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
            "codex": _doctor("codex", "AUTH_REQUIRED"),
            "busy": _doctor("busy"),
            "fallback": _doctor("fallback"),
        },
        {"busy": 1},
    )
    assert decision.agent_name == "fallback"


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
