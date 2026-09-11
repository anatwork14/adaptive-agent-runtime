# ARC Getting Started

The homepage contains the canonical installation and interactive demo flow. This file exists as a lightweight fallback for readers browsing the repository.

## Install

```bash
git clone https://github.com/anatwork14/adaptive-agent-runtime.git
cd adaptive-agent-runtime
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
arc --help
```

## Initialize

```bash
arc init . --project-id demo
arc status --project-id demo
```

## Smoke-test a real ARC task without provider credentials

Create `demo_arc.py`:

```python
import asyncio
import sqlite3
from pathlib import Path

from adapters.mock import MockAgentAdapter
from memory.lifecycle import MemoryLifecycle
from runtime.orchestrator import Orchestrator
from state.events import EventStore


async def main() -> None:
    repo = Path(".").resolve()
    db = repo / ".arc" / "state.db"
    store = EventStore(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    memory = MemoryLifecycle(conn)

    runtime = Orchestrator(
        event_store=store,
        memory_lifecycle=memory,
        repo_path=repo,
        project_id="demo",
    )
    runtime.create_task(
        task_id="hello-arc",
        goal="Create a traceable ARC demo artifact",
        files_declared=["arc_demo.txt"],
        acceptance_criteria=["arc_demo.txt is integrated through the gate"],
        risk=0.2,
    )

    result = await runtime.execute_task(
        "hello-arc",
        MockAgentAdapter("demo-agent"),
        agent_id="demo-agent",
    )
    print(result.status, result.merged_commit_sha)

    conn.close()
    store.close()


asyncio.run(main())
```

Run it from a clean git repository:

```bash
python demo_arc.py
arc status --project-id demo
arc events --project-id demo
arc replay --project-id demo
arc context build hello-arc --agent demo --project-id demo
```

To use Codex instead of the deterministic mock adapter, install and authenticate the Codex CLI, then replace `MockAgentAdapter("demo-agent")` with `CodexAgentAdapter()` from `adapters.codex`.
