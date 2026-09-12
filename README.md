# ARC — Adaptive Agent Runtime

> **A persistent multi-agent coding supervisor with reliable context, closed-loop review, isolated workers, and transactional integration.**

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

Authoritative project state lives in an append-only event stream plus Git state. Memory is a rebuildable, versioned projection used to compile bounded context for each task and worker. GitHub PR/check/review state is also treated as an external projection, never as project truth.

**ARC 0.7 closes the review loop.** Plain `arc` is a conversation-first coding supervisor; `arc ui` is the matching worker-centric browser workspace; persistent workers can publish their isolated branches as pull requests, ingest GitHub checks/reviews through the user's existing `gh` authentication, route new actionable feedback back into the same worker, and still converge on ARC's own exact-candidate integration gate.

**Status:** experimental / pre-alpha. Persistent workers, orchestration, event replay, review synchronization, Git isolation, and the transactional gate are implemented and tested with the deterministic mock executor. Real provider wrappers remain experimental; per-worker browser preview, stronger long-lived PTY supervision, provider sandboxing, remote multi-user security, learned planning/routing, and repository-scale evaluation remain active work.

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

Connect coding-agent accounts through their native login flows:

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

For GitHub review supervision, ARC uses the already-authenticated GitHub CLI:

```bash
gh auth login
gh auth status
```

ARC does not store GitHub tokens either.

---

## Use ARC like a coding-agent CLI

Run:

```bash
arc
```

The default experience is an interactive supervisor:

```text
ARC — persistent multi-agent coding supervisor

> add OAuth login, integration tests, and documentation

ARC planned 3 tasks:
  T001  implement OAuth backend      → builder
  T002  add integration tests        → builder
  T003  update authentication docs   → reviewer

> /open T001
Worker opened S_a1b2c3d4 → T001 / builder

> preserve the current session API and add refresh-token rotation
builder is working in T001…

> /diff
...

> /publish
PR #42  https://github.com/.../pull/42

> /review
PR #42  review=CHANGES_REQUESTED  failed=1

> /fix-review
GitHub feedback routed to the same worker and a new turn completed.

> /publish
PR #42 updated

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
/publish [SESSION]
/review [SESSION]
/fix-review [SESSION]
/submit [SESSION]
/stop [SESSION]
/run
/attach [SESSION]
/exit
```

---

## Persistent worker model

ARC separates authoritative work from its supervised draft environment:

```text
Task (authoritative)
  │
  ▼
WorkerSession
  ├── agent/profile/model
  ├── immutable ContextPacket
  ├── persistent isolated Git worktree
  ├── conversation transcript
  ├── changed files + draft diff
  ├── native terminal handoff
  └── external ReviewStatus
          │
          ▼
  exact immutable candidate
          │
          ▼
  transactional IntegrationGate
```

A conversation is not a patch. A PR is not an ARC completion signal. A green external CI run is not authoritative integration. ARC marks a task complete only after its exact candidate passes the ARC gate.

### Session persistence

ARC persists:

- worker/session identity;
- selected agent/provider/model;
- immutable initial ContextPacket;
- conversation turns;
- worktree path and branch;
- changed-file observations;
- PR/review projection events;
- submit/gate outcome;
- native terminal attach lifecycle events.

The event log and worktree survive ARC restarts. Provider PIDs do **not** pretend to be durable project state.

```bash
arc session list
arc session resume S_a1b2c3d4
arc session send S_a1b2c3d4 "continue by fixing the failing integration test"
```

### Scriptable worker lifecycle

```bash
arc session open T001 --agent builder
arc session list
arc session show S_a1b2c3d4
arc session send S_a1b2c3d4 "add edge-case tests"
arc session files S_a1b2c3d4
arc session diff S_a1b2c3d4
arc session resume S_a1b2c3d4
arc session publish S_a1b2c3d4
arc session review S_a1b2c3d4
arc session review S_a1b2c3d4 --apply
arc session submit S_a1b2c3d4
arc session stop S_a1b2c3d4
```

### Native provider UI

To use Codex / Claude / Antigravity / OpenCode directly while preserving ARC's worker workspace:

```bash
arc attach S_a1b2c3d4
```

ARC launches the provider's native terminal interface in that worker worktree and re-inspects changes when it exits. Authentication stays provider-owned. Drafts remain unintegrated until explicit ARC submit.

---

## Closed-loop GitHub review

The v0.7 review path is:

```text
WorkerSession
     │
     │ /publish
     ▼
worker Git branch ─────► GitHub PR
                            │
                   checks + reviews + comments
                            │
                            ▼
                    ARC review projection
                            │
                 append-only session.review_*
                            │
                    new actionable feedback
                            │
                            ▼
                    same owning worker
                            │
                     code/test fixes
                            │
                       push update
                            │
                            ▼
                   explicit ARC submit
                            │
                            ▼
                  exact IntegrationGate
```

ARC normalizes:

- PR state and URL;
- status/check rollup;
- review decision;
- PR comments;
- inline review comments with file/line where available;
- merge-state status.

Review snapshots and actionable feedback have separate digests. This prevents normal GitHub state churn from repeatedly feeding identical feedback to the agent.

### Continuous review supervision

Run in the foreground:

```bash
arc supervise
```

Automatically route **new** actionable feedback back into linked active workers:

```bash
arc supervise --auto-apply
```

One pass for scripting, cron, launchd, or systemd:

```bash
arc supervise --once
arc supervise --once --auto-apply
```

External review synchronization can stop and restart without losing PR linkage because normalized state is projected into ARC events.

### Multi-commit review branches

PR iteration naturally creates history:

```text
A  initial implementation
B  CI fix
C  reviewer-requested fix
```

ARC does not force-rewrite that public branch. At final submit, a multi-commit worker branch is represented by an unattached synthetic squash candidate whose tree equals the worker HEAD and whose parent is the worker/integration merge-base.

```text
review branch A-B-C ──tree──► synthetic candidate S
                                 │
                                 ▼
                            ARC gate verifies S
```

This preserves public review history while retaining ARC's invariant:

> **The gate verifies and integrates exactly one immutable candidate.**

A branch with no worker-authored changes still fails closed as a no-op.

---

## Visual workspace

Launch:

```bash
arc ui
```

Default address:

```text
http://127.0.0.1:8788
```

The session-centric Workspace contains:

- project orchestrator prompt;
- Working / Needs you / In review / Resolved worker board;
- provider readiness;
- **Chat** tab;
- **Files** tab;
- **Diff** tab;
- **Review** tab with PR/check/feedback state;
- **Context** tab for the immutable ContextPacket;
- **Events** tab for authoritative task/session/review trace;
- **Terminal** tab with trusted native attach command;
- Publish PR / Push update / Sync review / Apply feedback controls;
- explicit Submit / Stop controls;
- WebSocket event refresh.

The Workspace is localhost-only by default because ARC does not yet provide ARC-user auth/RBAC.

---

## Multi-agent orchestration

ARC retains the core correctness boundary:

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
READY frontier
        │
        ▼
capability / cost / load routing
        │
   ┌────┼───────────┐
   ▼    ▼           ▼
Codex Claude   Antigravity
   │    │           │
   └────┼───────────┘
        ▼
parallel isolated worktrees
        │
        ▼
immutable candidates
        │
        ▼
SERIALIZED INTEGRATION GATE
```

Plan and run a mission:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

Or execute the reachable frontier:

```bash
arc orchestrate
```

Inspect routing:

```bash
arc route T001 --policy quality
```

Routing considers capabilities, task type, provider readiness, concurrency load, cost/quality weights, and the selected routing policy.

The deterministic mock is a deliberate smoke-test baseline. ARC does not silently substitute mock when a configured capable real provider is unavailable.

See [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md).

---

## Interface hierarchy

### `arc`
Flagship conversation-first supervisor.

### `arc ui`
Flagship worker/session browser workspace.

### `arc supervise`
Closed-loop GitHub review supervisor.

### `arc dashboard`
Task-DAG/fleet terminal Mission Control.

### `arc web`
Lower-level v0.5 task/provider orchestration browser.

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

Provider adapters never silently fabricate a successful patch. ARC measures repository changes and uses Git objects as the integration boundary.

---

## Event-sourced trace

Worker/review events include:

```text
session.created
session.message
session.turn_started
session.turn_finished
session.resumed
session.terminal_started
session.terminal_stopped
session.pr_published
session.pr_updated
session.review_synced
session.review_feedback
session.review_feedback_applied
session.review_feedback_cleared
session.review_sync_failed
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

Chat, memory, and external review state are operational context. Task/Git/gate facts decide correctness.

---

## CLI surface

```text
# flagship product surfaces
arc
arc ui
arc supervise
arc shell
arc attach SESSION

# persistent workers
arc session open | list | show | send | files | diff | resume
arc session publish | review | submit | stop

# auth
arc login [PROVIDER]
arc logout PROVIDER
arc auth status [PROVIDER]

# task / orchestration automation
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

# configuration / inspection
arc agent list | add | remove | doctor | tune
arc config show | default-agent
arc context build | inspect
arc memory list | why | consolidate | rebuild-index
arc gate inspect

# lower-level mission control
arc dashboard
arc web
```

---

## Architecture

```text
                             ARC
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
       `arc`               `arc ui`        `arc supervise`
          │                   │                   │
          └────────────── SessionArcApplication ─┘
                              │
              ┌───────────────┼────────────────┐
              │               │                │
        WorkerSession     Planner/Router    ReviewLoop
              │               │                │
              └───────────────┼────────────────┘
                              ▼
                    authoritative Task DAG
                              │
                bounded immutable ContextPacket
                              │
                    isolated worker worktree
                              │
                   public review branch (optional)
                              │
                    exact candidate commit
                              │
                    serialized IntegrationGate
                              │
                    authoritative Git state
```

ARC deliberately separates authoritative truth from adaptive memory and external integrations. If deleting an index, summary, transcript projection, or review cache would erase what **actually happened**, that information was stored in the wrong place.

---

## Current implementation status

| Component | Status |
|---|---|
| SQLite WAL authoritative event store | ✅ |
| Deterministic task/project replay | ✅ |
| Persistent `WorkerSession` event model | ✅ |
| Persistent isolated worker worktrees | ✅ |
| Multi-turn worker conversation | ✅ |
| Session resume after ARC restart | ✅ |
| Changed-files + draft diff inspection | ✅ |
| Native provider-terminal handoff | ✅ |
| Conversation-first `arc` shell | ✅ |
| Session-centric `arc ui` workspace | ✅ |
| GitHub PR create/update through existing `gh` auth | ✅ v0.7 |
| CI / review / inline-comment ingestion | ✅ v0.7 |
| Review feedback routed to owning worker | ✅ v0.7 |
| Foreground multi-worker review supervisor | ✅ v0.7 |
| Review/feedback digest deduplication | ✅ v0.7 |
| Exact squash candidate for multi-commit review branches | ✅ v0.7 |
| Deterministic mission planner baseline | ✅ |
| Capability/cost/load-aware router | ✅ |
| Concurrent independent agent execution | ✅ |
| Serialized exact-candidate integration gate | ✅ |
| All-declared-file leases + fencing | ✅ |
| Native provider login orchestration | ✅ |
| Codex / Claude / Antigravity / OpenCode adapters | 🧪 experimental |
| Versioned memory + provenance | ✅ |
| Hard-budget ContextPacket compiler | ✅ |
| Docker-backed command/test sandbox | ✅ |
| Per-worker browser/application preview | 🚧 next |
| Stronger daemon / PTY supervision | 🚧 next |
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
├── application/    # app boundary, sessions, planning, routing, review loop
├── integrations/   # GitHub/external-system adapters
├── adapters/       # Codex/Claude/Antigravity/OpenCode + Mock
├── cli/            # product CLI and automation commands
├── tui/            # interactive shell + Mission Control
├── webui/          # ARC Workspace + lower-level browser control
├── context/        # retrieval, allocation, compiler, staleness
├── memory/         # lifecycle, provenance, supersession, consolidation
├── runtime/        # orchestrator, gate, leases, recovery, replay, budgets
├── state/          # authoritative event store + deterministic projections
├── isolation/      # Git worktrees and candidate boundaries
├── verification/   # checks, reviewer, test runner
├── indexes/        # FTS, deterministic vector baseline, symbols, relations
├── eval/           # baselines, faults, grading, statistics
├── tests/
└── docs/
```

---

## Research framing

ARC supports falsifiable questions around reliable context and orchestration:

> Can versioned, provenance-aware context control improve long-horizon coding reliability or reduce cost relative to transcript/static/vector-memory handoff at matched cost?

> Can adaptive task decomposition/routing/scheduling improve resolved rate, latency, or cost over deterministic orchestration policies without weakening integration correctness?

> Can replayable review feedback loops improve autonomous issue resolution without increasing unsafe test weakening, stale-context failures, or integration regressions?

Evaluation targets include:

```text
resolved rate @ iso-cost
end-to-end makespan
provider/task routing regret
tokens + USD per resolved task
retry / rejection rate
review iterations per resolution
feedback-to-fix latency
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
- dependency/overlap orchestration behavior;
- provider auth probes without real secrets;
- worker creation, turns, restart/resume, stop, submit and gate integration;
- GitHub review normalization with fake external responses;
- review feedback routing/deduplication;
- multi-commit review branch → exact synthetic candidate integration;
- Workspace review API behavior;
- Textual shell mounting;
- FastAPI/WebSocket flows.

Run locally:

```bash
python -m pytest -q
python -m build
```

---

## Security

ARC executes code produced by AI agents. Treat that as untrusted-code execution.

Provider credentials remain in provider-owned credential stores/keyrings. GitHub credentials remain owned by `gh`. ARC does not copy those tokens into `.arc/`, events, or browser payloads.

The command/test execution path can use Docker isolation with network disabled, dropped capabilities, resource limits, and a read-only root filesystem. Provider coding CLIs remain experimental host-mode because safely brokering vendor authentication into isolated containers requires additional design.

`arc ui` and `arc web` are local developer control surfaces, not authenticated multi-user services. Keep their default loopback bindings unless you place an appropriate trusted security boundary in front of them.

---

## Public website

Project homepage:

```text
https://anatwork14.github.io/adaptive-agent-runtime/
```

GitHub Pages deploys from `docs/`. The public documentation website is separate from local `arc ui` and `arc web` applications.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
