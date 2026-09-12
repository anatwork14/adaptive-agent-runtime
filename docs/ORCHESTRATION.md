# ARC Multi-Agent Orchestration — v0.5

ARC v0.5 turns the existing reliable execution runtime into a real multi-agent orchestrator.

The design rule is simple:

> **Parallelize agent work. Serialize authoritative integration.**

ARC can dispatch independent tasks to different coding-agent profiles at the same time, but it never allows concurrent agents to become independent writers of the integration branch.

## The execution model

```text
high-level objective
        │
        ▼
DeterministicPlanner
        │
        ▼
versioned Task DAG
        │
        ▼
READY task frontier
        │
        ▼
AgentRouter
 capability + quality + cost + load
        │
        ├────────────┬────────────┐
        ▼            ▼            ▼
     Codex         Claude     Antigravity
        │            │            │
        └──── parallel isolated work ────┘
                     │
                     ▼
              candidate commits
                     │
                     ▼
        SERIALIZED INTEGRATION GATE
                     │
              verify exact candidate
                     │
                accept/reject
                     │
                     ▼
              integration branch
```

Adaptive memory remains derived. The event stream, task DAG, Git state, leases, budgets, routing decisions, and gate outcomes remain authoritative.

## Quick start

After initializing ARC and configuring provider profiles:

```bash
arc init . --project-id demo
arc login codex --profile builder
arc login claude --profile reviewer
arc login antigravity --profile researcher
```

Inspect provider readiness:

```bash
arc auth status
arc agent doctor
```

Plan a high-level objective:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass"
```

This materializes a real task DAG. For the declared surfaces above the deterministic baseline planner creates an implementation task first, then test/docs tasks that depend on it.

Explain a routing decision without executing it:

```bash
arc route T001
```

Run all reachable work:

```bash
arc orchestrate
```

Or plan and run in one command:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

## Deterministic planner baseline

`DeterministicPlanner` is deliberately not presented as an intelligent LLM planner.

It exists because ARC needs a reproducible control condition for research and a safe zero-provider planning path for product use.

Current baseline behavior:

- no declared files → one implementation task;
- source files → grouped by top-level repository surface;
- tests → test tasks;
- documentation → docs tasks;
- test/docs work waits for relevant implementation work;
- task count is bounded by `--max-tasks`;
- planning output becomes normal authoritative `task.created` events;
- an `orchestration.plan_created` event records the plan mapping.

Future LLM/learned planners should implement the same mission-plan contract so they can be compared against this deterministic baseline.

## Explainable routing

Every `AgentProfile` may expose:

```yaml
capabilities:
  - implementation
  - test
max_concurrency: 2
cost_weight: 1.0
quality_weight: 1.2
```

ARC combines:

- hard required capabilities;
- task type;
- role match;
- provider readiness;
- current per-agent load;
- maximum concurrency;
- quality weight;
- cost weight;
- routing policy.

Supported policies:

```text
balanced
quality
cost
```

Configure the project defaults in `.arc/config.yaml`:

```yaml
orchestration_max_parallel: 3
routing_policy: balanced
```

Tune a named agent without changing its credentials:

```bash
arc agent tune builder \
  --capability implementation \
  --capability test \
  --max-concurrency 2 \
  --quality-weight 1.3 \
  --cost-weight 1.0
```

Inspect what ARC would choose:

```bash
arc route T001 --policy quality
```

The result includes the selected agent, policy score, and human-readable reasons.

### Mock is a deliberate fallback, never a disguise for provider failure

The built-in mock profile remains useful for deterministic smoke tests and CI. Automatic orchestration uses mock only when **no capable real executor profile is configured for the task**.

If a capable Codex/Claude/Antigravity/OpenCode profile is configured but is signed out, missing, disabled by load, or saturated, ARC defers the task and reports the routing failure instead of silently running mock. This keeps broken provider setup visible. Operators can still explicitly choose `--agent mock` when they intentionally want a smoke test.

## Concurrency model

ARC v0.5 distinguishes two kinds of concurrency.

### Parallel agent phase

Independent tasks can concurrently:

- compile task-specific ContextPackets;
- create isolated Git worktrees;
- call different provider CLIs;
- edit different declared repository surfaces;
- create immutable candidate commits.

The orchestration engine uses `asyncio.gather()` for the selected batch.

### Serialized gate phase

Candidate verification and final integration are protected by an explicit integration lock.

Only one candidate at a time may:

```text
fresh integration HEAD
       ↓
cherry-pick candidate
       ↓
static checks / configured tests / review
       ↓
accept or reject
       ↓
merge exact accepted candidate
```

This is intentional. Parallel final Git integration would weaken the single-writer correctness boundary.

## File-surface conflict control

ARC uses declared file surfaces as a first concurrency boundary.

Before dispatch, an executing task acquires exclusive leases for all declared files. If another active worker owns one of those files, lease acquisition fails closed and the task remains safely retryable.

Within an orchestration batch, tasks with overlapping declared surfaces are deferred instead of dispatched together.

Example:

```text
T001 → src/auth.py
T002 → src/payments.py
T003 → src/auth.py
```

ARC may dispatch T001 and T002 concurrently. T003 waits for a later round.

This is conservative by design. Future work can add symbol-level or semantic conflict prediction, but it must not remove the authoritative lease/fencing boundary.

## Dependency rounds

The engine repeatedly executes the READY frontier.

Example:

```text
T001 implementation ───────┐
                           ├─► T003 tests
T002 implementation ───────┘
```

Round 1 can execute T001 and T002 concurrently. Once they are accepted, deterministic replay marks T003 READY. Round 2 then routes and executes T003.

The engine stops when:

- no READY tasks remain; or
- READY work exists but no valid route can currently make progress.

It does not spin indefinitely on unroutable tasks.

## Orchestration event trace

Routing is not hidden application state. ARC emits orchestration events into the same authoritative project event stream:

```text
orchestration.plan_created
orchestration.run_started
orchestration.routed
orchestration.deferred
orchestration.batch_started
orchestration.task_finished
orchestration.task_failed
orchestration.run_finished
```

This lets the CLI, TUI, browser UI, replay tools, and research evaluation all observe the same decisions.

It also makes later learned-policy evaluation possible because ARC can compare policy decisions and downstream outcomes from recorded traces.

## Terminal Mission Control

Launch:

```bash
arc dashboard
```

v0.5 adds:

```text
a  run READY fleet through orchestration policy
g  run selected READY task using ARC routing
y  retry
x  cancel
r  refresh
q  quit
```

The system panel shows routing policy and maximum parallelism. READY task detail shows the current recommended route.

## Browser Mission Control

Launch:

```bash
arc web --open
```

The browser now exposes:

- **Plan objective** — create a deterministic task DAG;
- **Run ready** — route/execute the reachable fleet;
- **Explain route** — inspect agent selection reasons;
- the existing live task ledger;
- provider teams and readiness;
- authoritative WebSocket event trace.

The browser does not simulate orchestration animations. The live view is driven by actual runtime events.

Relevant API endpoints:

```text
POST /api/missions/plan
GET  /api/tasks/{task_id}/route
POST /api/orchestration/run
```

## Research baseline vs future intelligence

What v0.5 implements:

```text
planner       deterministic baseline
router        deterministic capability/cost/load policy
concurrency   real parallel agent work
integration   explicit single writer
events        replayable orchestration trace
```

What remains future research/product work:

- LLM planner with structured repair/replanning;
- learned/bandit routing from task/provider outcomes;
- dynamic provider cost/latency estimates;
- semantic/symbol-level conflict prediction;
- automatic reviewer selection;
- adaptive retry/escalation policies;
- rate-limit-aware scheduling;
- remote/distributed workers;
- repository-scale iso-cost orchestration benchmarks.

The deterministic v0.5 policies are intentionally retained as baselines even after smarter policies are added.
