"""Unit tests for BudgetAccountant."""

from runtime.budgets import BudgetAccountant
from state.events import EventStore


def test_budget_enforcement_and_ceilings(tmp_path):
    store = EventStore(tmp_path / "budget_test.db")
    accountant = BudgetAccountant(store, "p_budget", hard_task_usd=2.0, hard_project_usd=10.0)

    # Initially can spend 1.5
    assert accountant.can_spend("t1", 1.5) is True

    # Spend 1.5 on t1
    accountant.record_consumption(usd=1.5, tokens=2000, task_id="t1")

    # Now t1 cannot spend another 1.0 (1.5 + 1.0 > 2.0)
    assert accountant.can_spend("t1", 1.0) is False
    # But t2 can spend 0.4
    assert accountant.can_spend("t2", 0.4) is True

    # Check project exhaustion limit
    accountant.record_consumption(usd=8.5, tokens=10000, task_id="t2")
    events = store.read_all(project_id="p_budget")
    exhausted_events = [e for e in events if e.kind == "budget.exhausted"]
    assert len(exhausted_events) == 1

    store.close()
