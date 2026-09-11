# ARC Operator Guide

This guide documents the operator-facing ARC v0.2 surface: repository-local configuration, task lifecycle, named coding-agent profiles, live event monitoring, and terminal Mission Control.

## Operating model

All user interfaces call the same `ArcApplication` service layer. `ArcApplication` coordinates configuration and inspection, but the existing `Orchestrator` remains the single authoritative execution writer.

```text
                      ArcApplication
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
        CLI/Typer       TUI/Textual       future API
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                       Orchestrator
                            │
         authoritative events + Git integration
```

Adaptive memory remains derived and non-authoritative.

## Command map

```text
arc init
arc status
arc events
arc replay
arc run TASK
arc watch TASK
arc dashboard

arc task create
arc task list
arc task show
arc task run
arc task retry
arc task cancel

arc agent list
arc agent add
arc agent remove
arc agent doctor

arc config show
arc config default-agent

arc context build
arc context inspect

arc memory list
arc memory why
arc memory consolidate
arc memory rebuild-index

arc gate inspect
```

## Repository configuration

ARC stores configuration at:

```text
.arc/config.yaml
```

Example:

```yaml
project_id: my-project
default_agent: builder
hard_task_usd: 5.0
hard_project_usd: 500.0
visible_test_cmd:
  - python
  - -m
  - pytest
  - -q
agents:
  mock:
    name: mock
    provider: mock
    role: smoke-test
    enabled: true
  builder:
    name: builder
    provider: codex
    model: null
    role: implementation
    enabled: true
  reviewer:
    name: reviewer
    provider: claude
    model: null
    role: verification
    enabled: true
```

`.arc/` is automatically added to the repository-local `.git/info/exclude` file so runtime metadata does not dirty the integration tree.

## Named agent profiles

Create a Codex builder:

```bash
arc agent add builder \
  --provider codex \
  --role implementation \
  --default
```

Create a Claude verifier profile:

```bash
arc agent add reviewer \
  --provider claude \
  --role verification
```

Use a provider-specific command override when a local CLI version needs a different invocation:

```bash
arc agent add builder \
  --provider codex \
  --command 'codex exec --full-auto -'
```

Equivalent environment overrides remain supported by the adapters:

```bash
export ARC_CODEX_COMMAND='codex exec --full-auto -'
export ARC_CLAUDE_COMMAND='claude -p'
export ARC_OPENCODE_COMMAND='opencode run'
```

Check readiness without starting an agent:

```bash
arc agent doctor
arc agent doctor builder reviewer
```

Doctor states:

| State | Meaning |
|---|---|
| `READY` | local executable/profile is available |
| `MISSING` | required provider executable is absent |
| `GATEWAY_ONLY` | gateway exists but is not a filesystem coding executor |
| `UNCONFIGURED` | required gateway configuration is absent |
| `DISABLED` | profile is disabled |

OpenRouter intentionally remains `GATEWAY_ONLY`; ARC will not convert plain text completion into a fake repository patch.

## Task lifecycle

Create a task:

```bash
arc task create "Implement authentication middleware" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --accept "authentication tests pass" \
  --risk 0.6
```

Task IDs are generated as `T001`, `T002`, and so on unless `--id` is supplied.

Create a dependency:

```bash
arc task create "Add authentication tests" \
  --depends T001 \
  --file tests/test_auth.py
```

ARC leaves dependent tasks in `created` until all dependencies are completed; then the deterministic projection marks them `ready`.

Inspect:

```bash
arc task list
arc task show T001
```

Execute:

```bash
arc run T001 --agent builder
# equivalent
arc task run T001 --agent builder
```

Only `READY` tasks can execute. Execution goes through the normal ARC path: bounded context, isolated Git worktree, immutable candidate commit, fresh gate worktree, verification, and serialized integration.

Retry a failed or blocked task:

```bash
arc task retry T001 --reason "provider recovered"
```

This appends `recovery.retry`; it does not mutate the projected task row directly.

Cancel an unfinished task:

```bash
arc task cancel T001 --reason "scope removed"
```

This appends `task.abandoned` to authoritative history.

## Live monitoring

Monitor one task in a normal terminal:

```bash
arc watch T001
```

The view refreshes task state and recent events until the task reaches `completed`, `failed`, or `abandoned`. Use `Ctrl-C` to stop early.

For scripting or future APIs, the shared application layer also exposes `EventStream.poll()` and an asynchronous `EventStream.subscribe()` generator. Both read from the same SQLite append-only event store.

## Mission Control TUI

Launch:

```bash
arc dashboard
```

Mission Control contains:

```text
┌──────────────────────── ARC Mission Control ─────────────────────┐
│ TASK DAG                              │ AGENTS / SYSTEM           │
│ T001  implement auth   READY          │ ● builder   READY         │
│ T002  tests            CREATED        │ ○ reviewer  READY         │
├───────────────────────────────────────┼───────────────────────────┤
│ TASK DETAIL                           │ AUTHORITATIVE EVENT STREAM │
│ goal / agent / risk / files / events  │ #42 task.created          │
│                                       │ #43 task.dispatched       │
└───────────────────────────────────────┴───────────────────────────┘
```

Keyboard actions:

| Key | Action |
|---|---|
| `g` | execute selected READY task with the configured default agent |
| `y` | retry selected failed/blocked task |
| `x` | cancel selected unfinished task |
| `r` | force refresh |
| `q` | quit |

The TUI periodically reads a shared application snapshot and only issues mutations through `ArcApplication`. It does not own a parallel task database or memory representation.

## Context inspection

Compile the context a named agent would receive:

```bash
arc context inspect T001 --agent builder
```

The output includes the immutable packet ID/digest, project state version, delivered token count, derived memory categories, and code evidence count.

Risk may change context allocation, but never expands the task's hard token ceiling.

## Memory inspection

List active derived memory:

```bash
arc memory list
```

Inspect provenance:

```bash
arc memory why M_44
```

Consolidate eligible failure memories into procedures:

```bash
arc memory consolidate
```

Rebuild derived indexes:

```bash
arc memory rebuild-index
```

Deleting/rebuilding a derived index must not erase authoritative project truth.

## Gate inspection

```bash
arc gate inspect T001
```

The gate verifies the exact candidate commit in a fresh worktree before integrating that same candidate into the main integration tree. A rejected candidate is not promoted to durable project memory.

## Deterministic replay

```bash
arc replay
```

Replay rebuilds project/task/budget/lease projections from authoritative events. Materialized memory outputs are replayed as recorded data rather than regenerated by an LLM.

## Application API

For integrations that should not shell out to the CLI:

```python
import asyncio
from application.app import ArcApplication


async def main() -> None:
    with ArcApplication(".", "demo") as arc:
        arc.initialize()
        task = arc.create_task(
            "Create an example artifact",
            files=["example.txt"],
        )
        result = await arc.run_task(task.task_id, agent_name="mock")
        print(result.status, result.merged_commit_sha)


asyncio.run(main())
```

Future browser APIs should wrap this application boundary rather than directly manipulating `EventStore`, `MemoryLifecycle`, or the integration gate.

## Safety boundaries

ARC executes code produced by coding agents. The command/test sandbox can use Docker isolation, while provider CLI execution is still experimental host-mode. Do not expose sensitive host credentials or run untrusted provider-generated code in valuable working copies.

The intended next UI layer is a localhost web/API control plane built on the same `ArcApplication` and event-stream abstractions—not a separate runtime implementation.
