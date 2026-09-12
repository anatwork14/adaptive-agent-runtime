# ARC — Adaptive Agent Runtime

> **A persistent multi-agent coding supervisor with reliable context, isolated workers, and transactional integration.**

[![CI](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-6b7280.svg)](LICENSE)
[![Website](https://img.shields.io/badge/site-GitHub%20Pages-88f7c5.svg)](https://anatwork14.github.io/adaptive-agent-runtime/)

<p align="center">
  <img src="docs/assets/hero_banner.jpg" alt="ARC Adaptive Agent Runtime Hero Banner" width="100%">
</p>

<p align="center">
  <strong><a href="https://anatwork14.github.io/adaptive-agent-runtime/">Website</a></strong>
  · <strong><a href="docs/GETTING_STARTED.md">Getting started</a></strong>
  · <strong><a href="docs/INTERACTIVE_WORKSPACE.md">Interactive workspace</a></strong>
  · <strong><a href="docs/ORCHESTRATION.md">Orchestration</a></strong>
  · <strong><a href="docs/OPERATOR_GUIDE.md">Operator guide</a></strong>
</p>

ARC coordinates Codex, Claude Code, Antigravity, OpenCode, and deterministic local workers while keeping project truth outside chat history.

The core rule is:

> **Adaptive memory is never authoritative.**

Authoritative project state lives in an append-only event stream plus Git state. Memory is a rebuildable, versioned projection used to compile bounded context for each task and worker.

**ARC 0.6 makes the application conversation-first.** Plain `arc` opens a persistent coding-agent supervisor. Each focused task can own a long-lived worker session with an isolated worktree, conversation, changed files, diff, immutable context, event trail, and native provider-terminal handoff. `arc ui` opens the matching session-centric browser workspace.

**Status:** experimental / pre-alpha. Persistent worker sessions, orchestration, isolation, replay, and the transactional gate are implemented and tested with the deterministic mock executor. Real provider wrappers remain experimental; provider sandboxing, remote multi-user security, PR/CI integrations, browser previews, learned planning/routing, and repository-scale evaluation remain active work.

---

## Start here

Install from source:

```bash
git clone https://github.com/anatwork14/adaptive-agent-runtime.git
cd adaptive-agent-runtime
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Initialize a target repository:

```bash
cd /path/to/your/project
arc init . --project-id demo
```

Connect provider accounts through their native login flows:

```bash
arc login
```

or directly:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
arc auth status
arc agent doctor
```

ARC does not copy provider OAuth tokens into `.arc/`. Credentials stay in the vendor CLI/keyring that owns them.

### Use ARC like a coding-agent CLI

Run:

```bash
arc
```

The default experience is now an interactive supervisor:

```text
ARC — persistent multi-agent coding supervisor

> add OAuth login, integration tests, and documentation

ARC planned 3 tasks:
  T001  implement OAuth backend      → builder
  T002  add integration tests        → builder
  T003  update authentication docs   → reviewer

Type /run to execute the READY fleet,
or /open T001 to supervise one worker interactively.

> /open T001
Worker opened S_a1b2c3d4 → T001 / builder

> preserve the current session API and add refresh-token rotation
builder is working in T001…
...

> /diff
...

> /submit
ACCEPTED  gate=...
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

### Open the visual workspace

```bash
arc ui
```

Default address:

```text
http://127.0.0.1:8788
```

The Workspace is worker/session-centric:

```text
┌─────────────┬──────────────────────────────────────┬──────────────────────┐
│ ARC         │ PROJECT ORCHESTRATOR                 │ WORKER INSPECTOR     │
│             │                                      │                      │
│ Board       │ What should the team accomplish?     │ Chat                 │
│ Workers     │ [ Plan & delegate                 ]  │ Files                │
│ Agents      │                                      │ Diff                 │
│ Trace       │ Working | Needs you | Review | Done  │ Context              │
│             │                                      │ Events               │
│ Providers   │ worker cards                         │ Terminal             │
└─────────────┴──────────────────────────────────────┴──────────────────────┘
```

Open any READY task as a persistent worker, continue its conversation, inspect the draft, and explicitly submit it through ARC's gate.

---

## Persistent workers

ARC 0.6 adds a durable `WorkerSession` above the authoritative task DAG:

```text
Task
  │
  ▼
WorkerSession
  ├── agent profile
  ├── immutable ContextPacket
  ├── isolated Git worktree
  ├── conversation transcript
  ├── changed-file surface
  ├── current diff
  ├── native terminal handoff
  └── authoritative session events
          │
          ▼
      explicit submit
          │
          ▼
 transactional integration gate
```

A task remains the authoritative unit of work. The session is its supervised draft workspace.

### Session persistence model

ARC persists:

- worker/session identity;
- selected agent/provider/model;
- immutable initial ContextPacket;
- conversation turns;
- worktree path and branch;
- changed-file snapshots;
- submit/gate outcome;
- terminal attach state as events.

The worktree and event log survive ARC restarts. Provider processes are **not** treated as durable state. After restarting ARC, resume the session against the same worktree:

```bash
arc session list
arc session resume S_a1b2c3d4
arc session send S_a1b2c3d4 "continue by fixing the failing test"
```

This avoids pretending a PID or terminal process is authoritative state.

### Scriptable session commands

```bash
arc session open T001 --agent builder
arc session list
arc session show S_a1b2c3d4
arc session send S_a1b2c3d4 "add edge-case tests"
arc session files S_a1b2c3d4
arc session diff S_a1b2c3d4
arc session resume S_a1b2c3d4
arc session submit S_a1b2c3d4
arc session stop S_a1b2c3d4
```

### Native provider UI

To work directly in Codex / Claude / Antigravity / OpenCode while preserving ARC's worker workspace:

```bash
arc attach S_a1b2c3d4
```

ARC runs the provider's native terminal interface in that worker's isolated worktree, then records the resulting changed-file surface when the provider exits. Authentication and provider-native terminal behavior remain vendor-owned.

ARC still requires explicit `session submit` before draft changes cross the transactional integration gate.

---

## Multi-agent orchestration

ARC retains the v0.5 correctness boundary:

> **Parallelize agent work. Serialize authoritative integration.**

```text
                    high-level objective
                            │
                            ▼
                 deterministic planner
                            │
                            ▼
                    versioned Task DAG
                            │
                            ▼
                    READY task frontier
                            │
                            ▼
               capability/cost/load router
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Codex           Claude       Antigravity
             │              │              │
             └──── parallel isolated work ─┘
                            │
                            ▼
                     candidate commits
                            │
                            ▼
                SERIALIZED INTEGRATION GATE
                            │
                    exact-candidate verify
                            │
                       accept/reject
```

Run a reproducible mission plan:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

Or run the reachable READY frontier:

```bash
arc orchestrate
```

Inspect routing:

```bash
arc route T001 --policy quality
```

Routing considers required capabilities, task type, provider readiness, concurrency load, operator quality/cost weights, and the selected policy (`balanced`, `quality`, `cost`).

The deterministic mock executor is an intentional smoke-test fallback. If a capable real provider is configured but unavailable/auth-required/saturated, ARC defers rather than silently pretending success with mock.

See [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md).

---

## Interfaces

ARC now has a clear interface hierarchy.

### 1. `arc` — flagship interactive CLI

Conversation-first planning and persistent worker supervision.

### 2. `arc ui` — flagship visual workspace

Session-centric local web app with:

- project orchestrator prompt;
- Working / Needs you / In review / Resolved board;
- persistent worker cards;
- Chat tab;
- changed files;
- live diff;
- immutable ContextPacket inspection;
- authoritative worker/task events;
- native terminal attach instructions;
- explicit Open worker / Submit / Stop actions;
- provider readiness;
- live WebSocket event refresh.

### 3. `arc dashboard` — terminal mission control

Task-DAG and fleet-oriented Textual dashboard.

### 4. `arc web` — lower-level orchestration control

The earlier v0.5 task/provider dashboard remains available at port `8787` for route/context/fleet inspection.

Both browser surfaces are localhost-only by default because ARC does not yet provide ARC-user authentication/RBAC.

---

## Provider authentication and execution

| Provider | ARC provider | Native auth | Execution |
|---|---|---|---|
| OpenAI Codex | `codex` | ChatGPT / OpenAI OAuth | 🧪 experimental |
| Claude Code | `claude` | Anthropic OAuth | 🧪 experimental |
| Google Antigravity | `antigravity` | Google OAuth / secure keyring | 🧪 experimental |
| OpenCode | `opencode` | CLI-managed | 🧪 experimental |
| OpenRouter | `openrouter` | environment gateway | gateway only |
| Mock | `mock` | none | deterministic tests/smoke |

Useful commands:

```bash
arc login
arc auth status
arc agent doctor
arc agent tune builder --capability implementation --max-concurrency 2
```

Provider adapters never silently fabricate a patch. ARC measures actual worktree changes and uses Git candidate commits as the integration input.

---

## Event-sourced session and orchestration trace

Persistent-worker events include:

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

Orchestration events include:

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

Session conversations are useful operational history, but task/gate/Git facts remain authoritative for whether work is actually integrated.

---

## CLI surface

```text
# primary product interfaces
arc
arc ui
arc shell
arc attach SESSION
arc session open | list | show | send | files | diff | resume | submit | stop

# auth
arc login [PROVIDER]
arc logout PROVIDER
arc auth status [PROVIDER]

# task/orchestration automation
arc init
arc status
arc events
arc replay
arc run TASK
arc route TASK
arc orchestrate
arc watch TASK
arc mission plan
arc task create | list | show | run | retry | cancel

# configuration/inspection
arc agent list | add | remove | doctor | tune
arc config show | default-agent
arc context build | inspect
arc memory list | why | consolidate | rebuild-index
arc gate inspect

# lower-level mission-control interfaces
arc dashboard
arc web
```

---

## Application architecture

```text
                                ARC
                                 │
             ┌───────────────────┴───────────────────┐
             │                                       │
      interactive shell                         ARC Workspace
          `arc`                                    `arc ui`
             │                                       │
             └───────────────────┬───────────────────┘
                                 ▼
                       SessionArcApplication
                                 │
                  ┌──────────────┼───────────────┐
                  │              │               │
            WorkerSession    Planner/Router   Context/Memory
                  │              │               │
                  └──────────────┼───────────────┘
                                 ▼
                        authoritative Task DAG
                                 │
                    isolated agent/worktree phase
                                 │
                                 ▼
                         candidate commit
                                 │
                                 ▼
                   serialized IntegrationGate
                                 │
                       authoritative Git state
```

The UI does not own a separate task/session truth database. Worker sessions reconstruct from the same append-only project event stream.

---

## Runtime architecture and correctness

ARC separates authoritative truth from adaptive context optimization:

```text
AUTHORITATIVE STATE                    ADAPTIVE MEMORY
append-only events                     derived projection
task DAG + session trace               provenance
leases + budgets                       validity/supersession
candidate commits                      failure/procedure memory
gate outcomes                          retrieval indexes
        │                                      │
        └─────────────────┬────────────────────┘
                          ▼
                  CONTEXT COMPILER
             hard budget + code evidence
                          │
                          ▼
                immutable ContextPacket
                          │
                          ▼
             persistent isolated worktree
                          │
                          ▼
                  candidate commit
                          │
                          ▼
              serialized integration gate
```

If deleting ARC's derived memory/indexes would erase what **actually happened**, that information was stored in the wrong place.

---

## Current implementation status

| Component | Status |
|---|---|
| SQLite WAL authoritative event store | ✅ |
| Deterministic task/project replay | ✅ |
| Shared application service layer | ✅ |
| Persistent `WorkerSession` event model | ✅ v0.6 |
| Persistent isolated worker worktrees | ✅ v0.6 |
| Multi-turn worker conversation | ✅ v0.6 |
| Session resume after ARC restart | ✅ v0.6 |
| Changed-files + draft diff inspection | ✅ v0.6 |
| Native provider-terminal handoff | ✅ v0.6 |
| Conversation-first `arc` shell | ✅ v0.6 |
| Session-centric `arc ui` workspace | ✅ v0.6 |
| Deterministic mission planner baseline | ✅ |
| Capability/cost/load-aware router | ✅ |
| Concurrent independent agent execution | ✅ |
| Serialized integration gate | ✅ |
| All-declared-file leases + fencing | ✅ |
| Replayable orchestration decisions | ✅ |
| Native provider login orchestration | ✅ |
| Codex / Claude / Antigravity / OpenCode adapters | 🧪 experimental |
| Versioned memory + provenance | ✅ |
| Hard-budget ContextPacket compiler | ✅ |
| Git worktree isolation | ✅ |
| Docker-backed command/test sandbox | ✅ |
| GitHub PR / CI / review feedback loop | 🚧 next |
| Isolated browser preview per worker | 🚧 next |
| Long-lived provider PTY multiplexing | 🚧 future |
| Learned/LLM planner | 🚧 research |
| Learned/bandit routing | 🚧 research |
| Provider CLI credential/container boundary | 🚧 |
| Remote ARC auth / RBAC / multi-user mode | 🚧 |
| Semantic embedding provider | 🚧 |
| OpenRouter tool-using coding loop | 🚧 |
| Repository-scale iso-cost benchmark | 🚧 |

---

## Repository structure

```text
adaptive-agent-runtime/
├── application/    # app boundary, sessions, planning, routing, auth/config/events
├── adapters/       # Codex/Claude/Antigravity/OpenCode + deterministic Mock
├── cli/            # Typer commands + v0.6 product launcher
├── tui/            # interactive shell, Mission Control, login picker
├── webui/          # FastAPI + ARC Workspace + legacy orchestration dashboard
├── context/        # retrieval, allocation, compiler, staleness
├── memory/         # lifecycle, provenance, supersession, consolidation
├── runtime/        # orchestrator, gate, leases, recovery, replay, budgets
├── state/          # authoritative event store + projections
├── isolation/      # Git worktrees and execution boundaries
├── verification/   # checks, reviewer, test runner
├── indexes/        # FTS, deterministic vector baseline, symbols, relations
├── eval/           # baselines, faults, grading, statistics
├── tests/
└── docs/
```

---

## Research framing

ARC supports two related falsifiable questions:

> Can versioned, provenance-aware context control improve long-horizon coding reliability or reduce cost relative to transcript/static/vector-memory handoff at matched cost?

and:

> Can adaptive task decomposition/routing/scheduling improve resolved rate, latency, or cost over deterministic orchestration policies without weakening integration correctness?

Persistent sessions add another measurable axis: handoff/restart continuity can be evaluated without treating a provider process or full transcript as authoritative state.

Primary evaluation targets include:

```text
resolved rate @ iso-cost
end-to-end makespan
provider/task routing regret
tokens + USD per resolved task
retry / rejection rate
context staleness
handoff degradation
restart/session continuity
```

---

## CI and testing

CI runs on Python 3.11 and 3.12 and checks:

- package install/build;
- correctness-focused Ruff rules;
- public homepage + Mission Control + Workspace JavaScript syntax;
- full pytest suite;
- real Git worktree/candidate/gate integration using deterministic mock;
- multi-agent dependency/overlap behavior;
- provider auth probes without real secrets;
- persistent worker creation, turns, restart/resume, stop, submit and gate integration;
- Textual shell mounting;
- FastAPI Workspace session lifecycle;
- WebSocket event streaming.

Run locally:

```bash
python -m pytest -q
python -m build
```

---

## Security

ARC executes code produced by AI agents. Treat that as untrusted-code execution.

Provider credentials remain in provider-owned credential stores and secure keyrings. ARC does not copy those tokens into `.arc/` or either browser UI.

The command/test execution path can use Docker isolation with network disabled, dropped capabilities, resource limits, and a read-only root filesystem. Provider coding CLIs remain experimental host-mode because safely brokering provider authentication into isolated containers requires additional design.

`arc ui` and `arc web` are local developer control surfaces, not authenticated multi-user services. Keep their default loopback bindings unless you put an appropriate trusted security boundary in front of them.

---

## Public website

Project homepage:

```text
https://anatwork14.github.io/adaptive-agent-runtime/
```

GitHub Pages deploys from `docs/`. The public documentation website is separate from the local `arc ui` and `arc web` applications.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
