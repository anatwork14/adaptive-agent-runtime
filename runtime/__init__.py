"""Runtime and orchestration package."""

from runtime.budgets import BudgetAccountant
from runtime.gate import IntegrationGate
from runtime.leases import LeaseManager
from runtime.recovery import RecoveryEngine, RecoveryStrategy
from runtime.replay import ReplayEngine
from runtime.scheduler import TaskScheduler


def __getattr__(name: str):
    """Load the orchestrator lazily to keep low-level adapters acyclic."""
    if name == "Orchestrator":
        from runtime.orchestrator import Orchestrator

        return Orchestrator
    raise AttributeError(name)

__all__ = [
    "Orchestrator",
    "BudgetAccountant",
    "IntegrationGate",
    "LeaseManager",
    "RecoveryEngine",
    "RecoveryStrategy",
    "ReplayEngine",
    "TaskScheduler",
]
