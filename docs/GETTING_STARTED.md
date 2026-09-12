# ARC Getting Started

ARC exposes one event-sourced runtime through the CLI, terminal Mission Control, and localhost browser Agent Orchestration Control. ARC v0.5 can also turn one objective into a task DAG, route READY tasks across coding-agent profiles, and execute independent agent work concurrently while keeping final Git integration serialized.

## 1. Install

```bash
git clone https://github.com/anatwork14/adaptive-agent-runtime.git
cd adaptive-agent-runtime
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
arc --help
```

Requirements: Python 3.11+, Git, and a clean Git repository for the project ARC will operate on.

## 2. Initialize a project

From the target repository:

```bash
arc init . --project-id demo
arc status
```

ARC writes local runtime state under `.arc/` and automatically adds `.arc/` to the repository-local Git exclude file (`.git/info/exclude`). It does not force a committed `.gitignore` change.

## 3. Connect coding-agent accounts

Run:

```bash
arc login
```

ARC opens an arrow-key provider picker and then invokes the selected provider's native authentication flow. ARC does not receive, copy, or persist OAuth tokens.

You can skip the picker:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
```

Credentials remain in each provider CLI's own credential/keyring store.

Inspect account and execution readiness:

```bash
arc auth status
arc agent doctor
```

ARC distinguishes provider installation from provider authentication. Execution states include:

```text
READY
AUTH_REQUIRED
MISSING
GATEWAY_ONLY
DISABLED
```

`opencode` remains available as a CLI execution provider. `openrouter` remains gateway-only until ARC owns a filesystem tool loop for it.

## 4. Tune the fleet for routing

ARC v0.5 agent profiles carry routing metadata in addition to provider/model/role.

Provider profiles receive sensible default capabilities, which you can override:

```bash
arc agent tune builder \
  --capability implementation \
  --capability test \
  --max-concurrency 2 \
  --quality-weight 1.3 \
  --cost-weight 1.0

arc agent tune reviewer \
  --capability review \
  --capability docs \
  --quality-weight 1.4
```

Project defaults live in `.arc/config.yaml`:

```yaml
orchestration_max_parallel: 3
routing_policy: balanced
```

Available routing policies are `balanced`, `quality`, and `cost`.

The built-in mock remains available for deterministic smoke tests. Automatic routing chooses mock only when **no capable real executor profile is configured for that task**. If a capable real provider is configured but is signed out, missing, or saturated, ARC defers instead of hiding the provider problem behind mock execution.

## 5. Create one task manually

```bash
arc task create "Create a traceable ARC demo artifact" \
  --file arc_demo.txt \
  --accept "artifact integrates through the gate" \
  --risk 0.2
```

ARC auto-generates task IDs (`T001`, `T002`, ...). Inspect the DAG with:

```bash
arc task list
arc task show T001
```

Run it explicitly with a named profile:

```bash
arc run T001 --agent builder
```

Or ask ARC to explain the route it would choose:

```bash
arc route T001
```

The route output includes the selected agent, policy score, and reasons.

## 6. Plan a multi-agent mission

For a higher-level objective, declare the expected repository surfaces:

```bash
arc mission plan "Add authentication with tests and documentation" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass"
```

The v0.5 planner is deliberately deterministic and replayable. For this example it materializes source implementation first, then test/docs tasks that depend on the implementation task.

The generated plan is not hidden chat state. It becomes the normal authoritative task DAG plus an `orchestration.plan_created` event.

## 7. Run the READY fleet

Execute all currently reachable work:

```bash
arc orchestrate
```

Or combine planning and execution:

```bash
arc mission plan "Add authentication with tests and documentation" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

ARC may execute independent agent work concurrently, but candidate verification/final integration remains a single-writer critical section.

Conceptually:

```text
READY frontier
     │
     ▼
 capability/cost/load routing
     │
 ┌───┼───────────┐
 ▼   ▼           ▼
A1   A2          A3      parallel isolated agent work
 │    │           │
 └────┼───────────┘
      ▼
 candidate commits
      ▼
 serialized integration gate
      ▼
 integration branch
```

Tasks that declare overlapping file surfaces are not dispatched in the same batch. ARC defers the conflicting task to a later round and also acquires exclusive leases before dispatch.

See [`ORCHESTRATION.md`](ORCHESTRATION.md) for the full scheduling/routing contract.

## 8. Run a zero-credential orchestration smoke test

Every project starts with the deterministic `mock` profile so ARC itself can be validated without provider cost.

You can create tasks and run:

```bash
arc orchestrate
```

Mock is an automatic route only when no capable real executor profile is configured for that task. If you configured a capable Codex/Claude/Antigravity/OpenCode profile and it is unavailable, ARC will defer rather than silently replace it with mock. You can always intentionally run a smoke task with `arc run TASK --agent mock`.

The mock still writes a real repository change that must survive the normal worktree, candidate commit, verification, and integration path.

## 9. Watch missions live

For one task:

```bash
arc watch T001
```

For the full fleet, use the TUI or browser UI. All surfaces read the same append-only event stream, including:

```text
orchestration.run_started
orchestration.routed
orchestration.deferred
orchestration.batch_started
orchestration.task_finished
orchestration.run_finished
```

## 10. Open terminal Mission Control

```bash
arc dashboard
```

Keyboard controls:

```text
a  route and run the READY fleet
g  route and run selected READY task
y  retry selected failed/blocked task
x  cancel selected task
r  refresh
q  quit
```

The system panel shows routing policy and maximum parallelism. READY task detail shows ARC's current route recommendation.

## 11. Open browser Agent Orchestration Control

```bash
arc web --open
```

Then open:

```text
http://127.0.0.1:8787
```

The browser includes:

- ARC Root + provider orchestrator cards;
- real provider/profile readiness and authentication states;
- live task execution ledger;
- provider-grouped agent teams;
- **Plan objective** to materialize a task DAG;
- **Run ready** to orchestrate the reachable fleet;
- **Explain route** to inspect agent choice/score/reasons;
- mission/context inspection;
- authoritative WebSocket event trace.

The browser does not simulate orchestration. Its activity is driven by actual runtime events.

The browser never accepts provider API keys or OAuth tokens. Native interactive login remains a terminal/provider responsibility.

The web control plane is intentionally localhost-only by default. ARC refuses a non-loopback bind unless you explicitly supply `--allow-remote`; the current UI has no built-in remote-user authentication.

See [`WEB_MISSION_CONTROL.md`](WEB_MISSION_CONTROL.md) for API and security details.

## 12. Inspect and replay what ARC did

```bash
arc events
arc replay
arc context inspect T001 --agent builder
arc gate inspect T001
arc memory list
```

For a specific memory:

```bash
arc memory why M_44
```

Routing/planning decisions are deliberately event-visible so later learned policies can be evaluated against the deterministic v0.5 baseline.

For the full operator command reference and configuration format, see [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).
