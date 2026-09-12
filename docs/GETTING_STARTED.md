# ARC Getting Started

ARC 0.6 exposes one event-sourced coding runtime through two primary product interfaces:

```text
arc       → conversation-first terminal supervisor
arc ui    → session-centric browser workspace
```

The lower-level task/orchestration commands, terminal dashboard, and earlier `arc web` control surface remain available for automation and inspection.

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

ARC writes local runtime state under `.arc/` and adds `.arc/` to the repository-local Git exclude file (`.git/info/exclude`). It does not force a committed `.gitignore` change.

## 3. Connect coding-agent accounts

```bash
arc login
```

ARC opens its provider selector, then invokes the selected provider's own authentication flow. ARC does not receive, copy, or persist OAuth tokens.

Direct setup is also supported:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher

arc auth status
arc agent doctor
```

Provider credentials remain in the provider CLI/keyring that owns them.

## 4. Start ARC like Codex / Claude Code

Run only:

```bash
arc
```

You enter the persistent ARC supervisor. At project scope, normal text is interpreted as a high-level objective:

```text
> add OAuth login, integration tests, and update the authentication docs
```

ARC materializes a task DAG and shows routes. Then either let the fleet execute:

```text
/run
```

or supervise one task directly:

```text
/open T001
```

Once a worker is focused, ordinary text becomes its next instruction:

```text
> preserve the existing session API and add refresh-token rotation
```

Inspect the draft:

```text
/files
/diff
```

Submit only when ready:

```text
/submit
```

Important shell controls:

```text
/help
/status
/tasks
/sessions
/open TASK [AGENT]
/focus SESSION|TASK
/send SESSION TEXT
/files [SESSION]
/diff [SESSION]
/submit [SESSION]
/stop [SESSION]
/run
/attach [SESSION]
/exit
```

## 5. Understand persistent workers

Opening a task creates a `WorkerSession`:

```text
Task
  ↓
WorkerSession
  ├── selected agent/profile
  ├── immutable ContextPacket
  ├── isolated Git worktree
  ├── conversation history
  ├── changed files
  ├── draft diff
  ├── native terminal handoff
  └── session event trail
          ↓
     explicit submit
          ↓
  transactional ARC gate
```

The task remains authoritative. Chat output is never treated as proof that work succeeded.

Session/worktree state survives restarting ARC. The provider process itself is intentionally not treated as durable state.

Scriptable controls:

```bash
arc session open T001 --agent builder
arc session list
arc session show S_12345678
arc session send S_12345678 "add edge-case tests"
arc session files S_12345678
arc session diff S_12345678
arc session resume S_12345678
arc session submit S_12345678
arc session stop S_12345678
```

See [`INTERACTIVE_WORKSPACE.md`](INTERACTIVE_WORKSPACE.md).

## 6. Use the provider's native terminal UI inside the same worker

```bash
arc attach S_12345678
```

ARC opens Codex, Claude, Antigravity, or OpenCode in that worker's isolated worktree. When the native CLI exits, ARC re-inspects the draft surface.

The provider still owns its authentication and terminal behavior. ARC still owns the integration boundary: native-terminal changes remain unintegrated until `arc session submit`.

## 7. Open the visual Agent Workspace

```bash
arc ui
```

Default address:

```text
http://127.0.0.1:8788
```

The Workspace is organized around persistent workers:

```text
PROJECT ORCHESTRATOR
      ↓
Working | Needs you | In review | Resolved
      ↓
select worker
      ↓
Chat | Files | Diff | Context | Events | Terminal
```

From the UI you can:

- plan an objective;
- create focused tasks;
- run the READY fleet;
- open a READY task as a persistent worker;
- continue the worker conversation;
- inspect changed files and the live draft diff;
- inspect the immutable ContextPacket;
- inspect authoritative events;
- copy the native `arc attach SESSION` command;
- explicitly submit through the integration gate;
- stop/discard a draft worker.

`arc ui` is localhost-only by default. It does not currently implement ARC-user authentication/RBAC.

## 8. Configure routing

Agent profiles can carry capabilities and concurrency/cost/quality metadata:

```bash
arc agent tune builder \
  --capability implementation \
  --capability test \
  --max-concurrency 2 \
  --quality-weight 1.3 \
  --cost-weight 1.0
```

Project defaults live in `.arc/config.yaml`:

```yaml
orchestration_max_parallel: 3
routing_policy: balanced
```

Policies:

```text
balanced
quality
cost
```

The deterministic mock executor is only an automatic smoke fallback when no capable real executor profile is configured. ARC does not silently hide a broken configured provider by routing to mock.

## 9. Create and route tasks directly

```bash
arc task create "Create a traceable ARC demo artifact" \
  --file arc_demo.txt \
  --accept "artifact integrates through the gate" \
  --risk 0.2

arc task list
arc task show T001
arc route T001
```

Run explicitly:

```bash
arc run T001 --agent builder
```

Or open it as a persistent supervised worker:

```bash
arc session open T001 --agent builder
```

## 10. Plan and run an autonomous multi-agent mission

```bash
arc mission plan "Add authentication with tests and documentation" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

Or execute the current READY frontier:

```bash
arc orchestrate
```

Independent provider work may execute concurrently. Final verification/integration remains serialized.

```text
READY tasks
    ↓
router
    ↓
Codex ─┐
Claude ├─ parallel isolated work
AGY ───┘
    ↓
candidate commits
    ↓
SERIAL integration gate
```

Tasks with overlapping declared file surfaces are deferred rather than intentionally dispatched together.

See [`ORCHESTRATION.md`](ORCHESTRATION.md).

## 11. Lower-level monitoring surfaces

One task:

```bash
arc watch T001
```

Terminal mission control:

```bash
arc dashboard
```

The earlier provider/task-oriented browser control remains available:

```bash
arc web --open
```

at:

```text
http://127.0.0.1:8787
```

For new interactive use, prefer `arc` and `arc ui`.

## 12. Inspect and replay ARC state

```bash
arc events
arc replay
arc context inspect T001 --agent builder
arc gate inspect T001
arc memory list
arc memory why M_44
```

Persistent-session events are also in the authoritative stream:

```text
session.created
session.message
session.turn_started
session.turn_finished
session.resumed
session.terminal_started
session.terminal_stopped
session.submitted
session.accepted
session.rejected
session.failed
session.stopped
```

For the broader command/configuration reference, see [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).
