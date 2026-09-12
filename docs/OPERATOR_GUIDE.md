# ARC Operator Guide

This guide documents the ARC v0.5 operator surface: provider-native login, repository-local agent profiles, mission planning, explainable routing, concurrent fleet execution, authoritative task lifecycle, and terminal/browser Mission Control.

## Operating model

Every ARC interface calls the same `ArcApplication` boundary.

```text
                            ArcApplication
                                  │
             ┌────────────────────┼────────────────────┐
             │                    │                    │
        Planner/Router      task/context/memory    CLI/TUI/Web
             │                    │                    │
             └──────────── OrchestrationEngine ───────┘
                                  │
                       concurrent agent work
                                  │
                                  ▼
                            Orchestrator
                    explicit single integration writer
                                  │
                    authoritative events + Git
```

Adaptive memory remains derived and non-authoritative.

Provider authentication remains a separate vendor-owned boundary. ARC stores provider/profile metadata but does not store access tokens, refresh tokens, OAuth codes, or API keys.

## Command map

```text
arc init
arc login [codex|claude|antigravity]
arc logout PROVIDER
arc auth status [PROVIDER]

arc status
arc events
arc replay
arc run TASK
arc route TASK
arc orchestrate
arc watch TASK
arc dashboard
arc web --open

arc mission plan
arc task create | list | show | run | retry | cancel
arc agent list | add | remove | doctor | tune
arc config show | default-agent
arc context build | inspect
arc memory list | why | consolidate | rebuild-index
arc gate inspect
```

## Provider login

Normal setup:

```bash
arc login
```

ARC opens an interactive arrow-key picker, exits the picker, then launches the provider CLI's own authentication flow.

Direct forms:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
```

Inspect status:

```bash
arc auth status
arc agent doctor
```

Provider behavior:

| Provider | Executable | Native login delegation | Execution |
|---|---|---|---|
| Codex | `codex` | `codex login` | experimental real CLI adapter |
| Claude Code | `claude` | `claude auth login` | experimental real CLI adapter |
| Antigravity | `agy` | interactive `agy` account flow | experimental headless adapter |
| OpenCode | `opencode` | CLI-managed | experimental real CLI adapter |
| OpenRouter | — | environment gateway | gateway-only; no fake filesystem executor |

Typical doctor states:

```text
READY
AUTH_REQUIRED
MISSING
GATEWAY_ONLY
UNCONFIGURED
DISABLED
```

## Repository configuration

ARC stores non-secret project configuration in:

```text
.arc/config.yaml
```

Example v0.5 configuration:

```yaml
project_id: my-project
default_agent: builder
hard_task_usd: 5.0
hard_project_usd: 500.0
orchestration_max_parallel: 3
routing_policy: balanced
visible_test_cmd:
  - python
  - -m
  - pytest
  - -q
agents:
  mock:
    name: mock
    provider: mock
    role: implementation
    capabilities: [implementation, test, docs, review, research]
    max_concurrency: 4
    cost_weight: 0.0
    quality_weight: 0.5
  builder:
    name: builder
    provider: codex
    role: implementation
    capabilities: [implementation, test]
    max_concurrency: 2
    cost_weight: 1.0
    quality_weight: 1.2
  reviewer:
    name: reviewer
    provider: claude
    role: review
    capabilities: [review, docs]
    max_concurrency: 1
    cost_weight: 1.2
    quality_weight: 1.4
```

`.arc/` is added to repository-local `.git/info/exclude`, so runtime metadata does not dirty the integration tree.

## Routing metadata

Profiles have provider/model information plus routing metadata:

```text
role
capabilities
max_concurrency
cost_weight
quality_weight
```

Provider defaults are populated automatically when capabilities are omitted, and operators can override them:

```bash
arc agent tune builder \
  --capability implementation \
  --capability test \
  --max-concurrency 2 \
  --quality-weight 1.3 \
  --cost-weight 1.0
```

Routing policies:

```text
balanced
quality
cost
```

The current router is deterministic. Required capabilities are hard constraints; provider readiness and concurrency saturation are also enforced. The selected result includes a score and human-readable reasons.

Inspect without running:

```bash
arc route T001
arc route T001 --policy quality
```

The built-in mock adapter is automatic fallback only when no eligible real READY coding-agent profile can satisfy the task.

## Task lifecycle

Create manually:

```bash
arc task create "Implement authentication middleware" \
  --file src/auth.py \
  --accept "authentication tests pass" \
  --risk 0.6
```

Dependencies:

```bash
arc task create "Add authentication tests" \
  --depends T001 \
  --file tests/test_auth.py
```

Inspect:

```bash
arc task list
arc task show T001
```

Execute explicitly:

```bash
arc run T001 --agent builder
```

Retry and cancellation remain event-sourced:

```bash
arc task retry T001 --reason "provider recovered"
arc task cancel T001 --reason "scope removed"
```

## Mission planning

ARC v0.5 provides a deterministic, replayable planning baseline:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass"
```

The baseline planner separates declared source/test/docs surfaces and builds a dependency DAG. It is intentionally not described as an intelligent LLM planner.

Planning produces normal `task.created` events plus:

```text
orchestration.plan_created
```

This baseline remains useful when future LLM/learned planners are introduced because it provides a reproducible control condition.

See [`ORCHESTRATION.md`](ORCHESTRATION.md) for the detailed contract.

## Fleet orchestration

Run all currently reachable work:

```bash
arc orchestrate
```

Or plan and immediately run:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --run
```

### Concurrency boundary

ARC parallelizes the expensive provider/agent phase for independent tasks:

```text
READY tasks
    │
    ▼
route + conflict filter
    │
 ┌──┼────────────┐
 ▼  ▼            ▼
A1  A2           A3
 │   │            │
parallel isolated worktrees
 │   │            │
 └───┼────────────┘
     ▼
candidate commits
     ▼
SERIALIZED integration gate
```

Final candidate verification/integration remains under an explicit single-writer lock.

### File leases

Before authoritative dispatch, a task acquires exclusive leases for all declared file surfaces. A conflicting lease fails closed. Within the same planned batch, tasks with overlapping declared files are deferred to a later round.

This is conservative on purpose. Future symbol/semantic conflict prediction may improve concurrency, but must not remove the authoritative lease/fencing boundary.

### Dependency rounds

Once accepted tasks complete, deterministic replay can unlock dependent tasks. The orchestration engine then selects the next READY frontier and continues until no route can make progress.

### Orchestration trace

ARC records:

```text
orchestration.run_started
orchestration.routed
orchestration.deferred
orchestration.batch_started
orchestration.task_finished
orchestration.task_failed
orchestration.run_finished
```

These events make routing/scheduling decisions observable to replay, UIs, debugging, and research evaluation.

## Live monitoring

One task:

```bash
arc watch T001
```

For the full fleet, use the TUI or browser UI. Both consume the same authoritative event stream.

## Terminal Mission Control

```bash
arc dashboard
```

Keyboard actions:

| Key | Action |
|---|---|
| `a` | route and execute the READY fleet |
| `g` | route and execute selected READY task |
| `y` | retry selected failed/blocked task |
| `x` | cancel selected unfinished task |
| `r` | force refresh |
| `q` | quit |

The TUI shows provider capabilities/max concurrency, project routing policy, maximum parallelism, route recommendations, and orchestration events.

## Browser Agent Orchestration Control

Launch:

```bash
arc web --open
```

The browser exposes:

- provider/orchestrator cards;
- live task ledger;
- provider-grouped teams;
- **Plan objective**;
- **Run ready**;
- **Explain route**;
- mission/context inspection;
- authoritative WebSocket event trace.

The orchestration controls call the same `ArcApplication` methods used by CLI/TUI. They do not implement a parallel browser-only scheduler.

v0.5 API endpoints:

```text
POST /api/missions/plan
GET  /api/tasks/{task_id}/route
POST /api/orchestration/run
```

The browser never accepts provider credentials and remains localhost-first. Non-loopback binding requires explicit `--allow-remote`; remote-user authentication/authorization is not yet a production boundary.

## Context, memory, and gate inspection

```bash
arc context inspect T001 --agent builder
arc memory list
arc memory why M_44
arc memory consolidate
arc memory rebuild-index
arc gate inspect T001
```

During concurrent runs, accepted-task memory materialization is scoped to that task's event trail so one worker does not accidentally ingest another concurrent worker's events.

A rejected candidate is not promoted to durable project memory.

## Deterministic replay

```bash
arc replay
```

Replay rebuilds project/task/budget/lease state from authoritative events. Recorded materialized memory is replayed as data rather than regenerated by an LLM.

## Safety boundaries

ARC executes agent-produced code. Provider CLI execution remains experimental host-mode even though command/test execution can use Docker isolation.

Provider credentials remain in vendor-owned stores. ARC's repository configuration must stay non-secret.

The integration branch remains single-writer even when provider work is concurrent.
