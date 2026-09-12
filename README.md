# ARC — Adaptive Agent Runtime

> **A persistent multi-agent coding supervisor with reliable context, closed-loop review, isolated workers, durable local runtimes, least-privilege execution, and transactional integration.**

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
  · <strong><a href="docs/PERSISTENT_RUNTIMES.md">Persistent runtimes</a></strong>
  · <strong><a href="docs/EXECUTION_SECURITY.md">Execution security</a></strong>
  · <strong><a href="docs/CLOSED_LOOP_REVIEWS.md">Closed-loop reviews</a></strong>
  · <strong><a href="docs/ORCHESTRATION.md">Orchestration</a></strong>
</p>

ARC coordinates Codex, Claude Code, Antigravity, OpenCode, and deterministic local workers while keeping project truth outside chat history.

The core rule is:

> **Adaptive memory is never authoritative.**

The same rule extends to external review and live processes. Authoritative project state lives in ARC's append-only event stream plus Git state. Memory, GitHub review state, runtime liveness, preview readiness, and UI projections are rebuildable or externally observable operational context.

**ARC 0.9 hardens the execution boundary built in 0.8.** Worker/provider subprocesses no longer inherit the whole ARC host environment. ARC constructs provider-scoped environments, lets profiles opt in extra variable names without storing values, starts previews without provider credentials, keeps profile command overrides process-local, and uses a private single-use handoff so tmux does not receive secret values in worker argv. Every path still converges on ARC's exact-candidate IntegrationGate before project state becomes complete.

**Status:** experimental / pre-alpha. Persistent workers, orchestration, event replay, GitHub review synchronization, tmux runtime supervision, localhost worker previews, least-privilege environment propagation, Git isolation, and the transactional gate are implemented and covered by deterministic tests. Real provider wrappers remain experimental. Provider processes are still host-mode and do not yet have full filesystem/network sandboxing. Remote multi-user security, learned planning/routing, semantic retrieval, desktop packaging, and repository-scale evaluation remain active work.

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

ARC does not copy provider OAuth tokens into `.arc/`. Credentials remain in the vendor CLI/keyring that owns them.

For GitHub review supervision, ARC uses your existing authenticated GitHub CLI:

```bash
gh auth login
gh auth status
```

For persistent PTY / preview supervision, install tmux:

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y tmux

# macOS
brew install tmux
```

### Least-privilege worker environment

ARC forwards a small runtime environment plus provider-specific credential variables instead of inheriting every host variable. If a worker needs an additional host variable, opt in its **name**:

```bash
arc env-policy builder
arc env-policy builder --allow INTERNAL_REGISTRY_HOST --allow CUSTOM_TOOL_HOME
arc env-policy builder --clear
```

ARC reads values from the live host environment when the worker starts. It does not persist or print those values through this policy surface. See [docs/EXECUTION_SECURITY.md](docs/EXECUTION_SECURITY.md).

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

> preserve the current API and add refresh-token rotation
builder is working in T001…

> /diff
...

> /publish
PR #42  https://github.com/.../pull/42

> /review
PR #42  review=CHANGES_REQUESTED  failed=1

> /fix-review
New actionable GitHub feedback was routed to the same worker.

> /publish
PR #42 updated

> /submit
ACCEPTED  gate=...
```

Core interactive controls:

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

ARC separates authoritative work from its supervised draft/runtime environment:

```text
Task (authoritative)
  │
  ▼
WorkerSession
  ├── agent/profile/model
  ├── immutable ContextPacket
  ├── isolated persistent Git worktree
  ├── multi-turn conversation
  ├── changed files + diff
  ├── optional GitHub ReviewStatus
  ├── optional tmux provider PTY
  └── optional localhost app preview
          │
          ▼
 exact immutable Git candidate
          │
          ▼
 transactional IntegrationGate
          │
          ▼
 authoritative Git + ARC events
```

A conversation is not a patch. A green PR is not ARC completion. A running preview is not correctness. A terminal process is not authoritative state. Only an exact candidate accepted by ARC's gate completes project work.

### Session persistence

ARC persists or can reconstruct:

- worker/session identity;
- selected agent/provider/model;
- immutable initial ContextPacket;
- conversation turns;
- worktree path and branch;
- changed-file observations;
- PR/review projection events;
- runtime start/stop metadata;
- submit/gate outcome.

The event log and worktree survive ARC restarts. A tmux runtime may also remain alive, but its raw PID is never persisted as project truth.

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
arc session review S_a1b2c3d4 --apply
arc session submit S_a1b2c3d4
arc session stop S_a1b2c3d4
```

---

## Persistent provider terminals

ARC retains the synchronous provider handoff:

```bash
arc attach S_a1b2c3d4
```

Since 0.8 ARC also supports a persistent PTY owned by tmux:

```bash
arc terminal S_a1b2c3d4
```

Start without immediately attaching:

```bash
arc terminal S_a1b2c3d4 --start-only
```

Inspect or stop it:

```bash
arc session terminal-status S_a1b2c3d4
arc session terminal-stop S_a1b2c3d4
```

The tmux session name is deterministic from the ARC worker session, so ARC can rediscover a still-running terminal after the command that launched it has exited.

The persistence boundary is:

```text
ARC event log      durable/replayable metadata
tmux session       live PTY/process ownership
PID                non-authoritative ephemeral state
```

ARC 0.9 additionally scrubs the worker environment through a mode-0600 single-use handoff before the long-lived provider process starts; secret environment values are not embedded in the tmux worker command line.

See [docs/PERSISTENT_RUNTIMES.md](docs/PERSISTENT_RUNTIMES.md) and [docs/EXECUTION_SECURITY.md](docs/EXECUTION_SECURITY.md).

---

## Per-worker application previews

Run a dev server directly inside the selected worker worktree:

```bash
arc session preview-start S_a1b2c3d4 \
  --command "npm run dev -- --host {host} --port {port}" \
  --port 3000
```

A zero-dependency Python example:

```bash
arc session preview-start S_a1b2c3d4 \
  --command "python -m http.server {port} --bind {host}" \
  --port 3000
```

Inspect or stop:

```bash
arc session preview-status S_a1b2c3d4
arc session preview-stop S_a1b2c3d4
```

ARC requires both `{host}` and `{port}` placeholders so the runtime owns the bind endpoint. Preview hosts are restricted to loopback:

```text
127.0.0.1
localhost
::1
```

Public binds such as `0.0.0.0` are rejected.

The preview remains on a different browser origin from ARC itself:

```text
ARC control plane   http://127.0.0.1:8788
worker preview      http://127.0.0.1:3000
```

ARC does not reverse-proxy arbitrary application content through the privileged Workspace origin, and ARC does not inject provider API credentials into preview processes.

---

## Closed-loop GitHub review

The review path is:

```text
WorkerSession
     │
     │ publish
     ▼
worker branch ─────────► GitHub PR
                             │
                    checks/reviews/comments
                             │
                             ▼
                    ARC review projection
                             │
                replayable session.review_*
                             │
                   new actionable feedback
                             │
                             ▼
                    same owning worker
                             │
                      fix + push update
                             │
                             ▼
                    explicit ARC submit
                             │
                             ▼
                    exact IntegrationGate
```

ARC normalizes PR state, checks, review decisions, PR comments, inline review comments, and merge-state status. Snapshot state and actionable feedback use separate digests so unrelated GitHub state churn cannot repeatedly feed identical feedback to a worker.

Continuous supervision:

```bash
arc supervise
arc supervise --auto-apply
arc supervise --once --auto-apply
```

### Multi-commit review branches

PR iteration may produce:

```text
A  initial implementation
B  CI fix
C  reviewer-requested fix
```

ARC does not rewrite public review history. At final submit it creates an unattached synthetic squash candidate whose tree equals worker HEAD and whose parent is the worker/integration merge-base:

```text
review branch A-B-C ──tree──► synthetic candidate S
                                 │
                                 ▼
                         IntegrationGate verifies S
```

The invariant remains:

> **The gate verifies and integrates exactly one immutable candidate.**

---

## Visual Workspace

Launch:

```bash
arc ui
```

Default:

```text
http://127.0.0.1:8788
```

The worker-centric Workspace contains:

- project orchestrator prompt;
- Working / Needs you / In review / Resolved board;
- provider readiness;
- **Chat** — continue the worker;
- **Files** — changed-file surface;
- **Diff** — current draft;
- **Preview** — start/stop localhost app, output tail, embedded preview, open-in-new-tab;
- **Review** — PR/check/feedback state and publish/sync/apply controls;
- **Context** — immutable ContextPacket;
- **Events** — authoritative task/session/review/runtime trace;
- **Terminal** — persistent tmux state, log tail, Start/Stop, attach command;
- explicit Submit / Stop controls;
- WebSocket event refresh.

Preview application content is loaded directly from its own localhost origin rather than through the ARC API server.

---

## Runtime lifecycle invariant

An ARC-managed live process must not intentionally outlive the worktree it owns.

Submit and stop therefore follow:

```text
stop preview
    ↓
stop persistent terminal
    ↓
submit/gate OR stop worker
    ↓
remove worktree when lifecycle permits
```

Workspace runtime mutations use the same per-worker action lock as other supervised actions so a runtime start/stop cannot race a simultaneous worker action.

Runtime status remains inspectable from events even after an accepted/stopped worker has had its draft worktree removed.

---

## Multi-agent orchestration

ARC's central execution rule remains:

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
   ┌────┼────────────┐
   ▼    ▼            ▼
Codex Claude    Antigravity
   │    │            │
   └────┼────────────┘
        ▼
parallel isolated worktrees
        │
        ▼
immutable candidates
        │
        ▼
SERIALIZED INTEGRATION GATE
```

Plan and execute a mission:

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

Or run the reachable frontier:

```bash
arc orchestrate
```

Inspect routing:

```bash
arc route T001 --policy quality
```

The deterministic mock is a deliberate smoke-test baseline. ARC does not silently substitute mock when a configured capable real provider is unavailable.

---

## Interface hierarchy

### `arc`
Flagship conversation-first supervisor.

### `arc ui`
Worker/session browser Workspace with review, preview, and runtime controls.

### `arc supervise`
Closed-loop GitHub review supervisor.

### `arc terminal SESSION`
Persistent tmux-backed provider terminal for one worker.

### `arc env-policy AGENT`
Inspect or replace additional environment-variable names explicitly forwarded to a profile.

### `arc dashboard`
Task-DAG/fleet terminal Mission Control.

### `arc web`
Lower-level task/provider orchestration browser.

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

Provider adapters never silently fabricate a successful patch. ARC measures repository changes and uses Git objects as its integration boundary. ARC 0.9 also prevents one provider from receiving another provider's environment credentials by default.

---

## Event-sourced trace

Worker/review/runtime events include:

```text
session.created
session.message
session.turn_started
session.turn_finished
session.resumed
session.terminal_started
session.terminal_stopped
session.runtime_started
session.runtime_stopped
session.terminal_attached
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

Runtime events store sanitized command metadata and environment-variable **names**, never values. Obvious secret-valued command arguments are redacted before persistence.

Chat, adaptive memory, review state, terminal output, and preview readiness are operational context. Task/Git/gate facts determine correctness.

---

## CLI surface

```text
# flagship surfaces
arc
arc ui
arc supervise
arc terminal SESSION
arc env-policy AGENT
arc shell
arc attach SESSION

# persistent workers
arc session open | list | show | send | files | diff | resume
arc session publish | review | submit | stop
arc session terminal-status | terminal-stop
arc session preview-start | preview-status | preview-stop

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

# lower-level mission control
arc dashboard
arc web
```

---

## Architecture

```text
                                  ARC
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        │                          │                           │
      `arc`                     `arc ui`                `arc supervise`
        │                          │                           │
        └────────────────── SessionArcApplication ─────────────┘
                                   │
             ┌─────────────────────┼──────────────────────┐
             │                     │                      │
       WorkerSession          ReviewLoop             WorkerRuntime
             │                     │                      │
             │                 GitHub PR            tmux backend
             │                                        │       │
             │                                   provider   preview
             │                                      PTY      server
             └─────────────────────┬──────────────────────┘
                                   ▼
                         authoritative Task DAG
                                   │
                         immutable ContextPacket
                                   │
                         isolated worker worktree
                                   │
                          exact Git candidate
                                   │
                      serialized IntegrationGate
                                   │
                         authoritative Git state
```

If deleting an index, summary, transcript projection, review cache, or tmux session would erase what **actually happened**, that information was stored in the wrong place.

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
| Synchronous native provider-terminal handoff | ✅ |
| tmux-backed persistent provider PTY | ✅ v0.8 |
| Live runtime rediscovery after ARC restart | ✅ v0.8 |
| Per-worker loopback browser/application preview | ✅ v0.8 |
| Runtime cleanup before worktree deletion | ✅ v0.8 |
| Least-privilege worker environment propagation | ✅ v0.9 |
| Provider-scoped default environment credentials | ✅ v0.9 |
| Value-free profile environment allowlist | ✅ v0.9 |
| Private single-use tmux environment handoff | ✅ v0.9 |
| Conversation-first `arc` shell | ✅ |
| Session-centric `arc ui` Workspace | ✅ |
| GitHub PR create/update through existing `gh` auth | ✅ v0.7 |
| CI / review / inline-comment ingestion | ✅ v0.7 |
| Review feedback routed to owning worker | ✅ v0.7 |
| Foreground multi-worker review supervisor | ✅ v0.7 |
| Review/feedback digest deduplication | ✅ v0.7 |
| Exact candidate for multi-commit review branches | ✅ v0.7 |
| Deterministic mission planner baseline | ✅ |
| Capability/cost/load-aware router | ✅ |
| Concurrent independent agent execution | ✅ |
| Serialized exact-candidate integration gate | ✅ |
| All-declared-file leases + fencing | ✅ |
| Native provider login orchestration | ✅ |
| Codex / Claude / Antigravity / OpenCode adapters | 🧪 experimental |
| Versioned adaptive memory + provenance | ✅ |
| Hard-budget ContextPacket compiler | ✅ |
| Docker-backed command/test sandbox | ✅ |
| Provider filesystem/network sandbox | 🚧 future |
| Remote ARC auth / RBAC / multi-user mode | 🚧 future |
| Learned/LLM planner | 🚧 research |
| Learned/bandit routing | 🚧 research |
| Semantic embedding provider | 🚧 research |
| OpenRouter tool-using coding loop | 🚧 |
| Repository-scale iso-cost benchmark | 🚧 research |
| Desktop packaging | 🚧 future |

---

## Repository structure

```text
adaptive-agent-runtime/
├── application/    # app boundary, workers, runtime supervision, planning, review loop
├── integrations/   # GitHub/external-system adapters
├── adapters/       # Codex/Claude/Antigravity/OpenCode + Mock
├── cli/            # product CLI and automation commands
├── tui/            # interactive shell + Mission Control
├── webui/          # ARC Workspace + runtime/review APIs + lower-level browser control
├── context/        # retrieval, allocation, compiler, staleness
├── memory/         # lifecycle, provenance, supersession, consolidation
├── runtime/        # orchestrator, env policy, tmux, gate, leases, recovery, replay, budgets
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

ARC supports falsifiable questions around reliable context, orchestration, and long-horizon supervision:

> Can versioned, provenance-aware context control improve long-horizon coding reliability or reduce cost relative to transcript/static/vector-memory handoff at matched cost?

> Can adaptive task decomposition/routing/scheduling improve resolved rate, latency, or cost over deterministic orchestration policies without weakening integration correctness?

> Can replayable review feedback loops and persistent supervised workspaces improve autonomous issue resolution without increasing unsafe test weakening, stale-context failures, or integration regressions?

Primary evaluation targets include:

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
- GitHub review normalization, routing, and deduplication with fake external responses;
- multi-commit review branch → exact synthetic candidate integration;
- fake-tmux terminal/preview start/status/stop;
- live runtime rediscovery after recreating ARC application state;
- loopback preview enforcement;
- runtime cleanup ordering before worktree deletion;
- provider subprocess environment isolation;
- provider-to-provider secret separation;
- preview credential exclusion;
- private tmux environment handoff and handoff deletion;
- environment-policy CLI persistence without value persistence;
- Workspace runtime/review API behavior;
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

ARC-managed coding-agent subprocesses now receive explicit least-privilege environments instead of the full host environment. Provider defaults are scoped by provider, profile extensions store names only, preview servers receive no automatic provider credentials, and tmux receives secret values through a private single-use handoff rather than worker argv. Runtime traces record environment names only.

The command/test execution path can use Docker isolation with network disabled, dropped capabilities, resource limits, and a read-only root filesystem. Provider coding CLIs remain experimental host-mode: environment isolation reduces ambient authority but does not prevent a provider process from accessing other files, networks, sockets, or provider-owned credential files available to the launching user.

Persistent tmux runtimes are local developer processes, not a sandbox. Preview servers are restricted to loopback and are not reverse-proxied through ARC. Preview application content therefore remains on a separate browser origin from the Workspace control plane.

`arc ui` and `arc web` are local developer control surfaces, not authenticated multi-user services. Keep their default loopback bindings unless you place an appropriate trusted security boundary in front of them.

See [docs/EXECUTION_SECURITY.md](docs/EXECUTION_SECURITY.md) for the exact 0.9 boundary and non-goals.

---

## Public website

Project homepage:

```text
https://anatwork14.github.io/adaptive-agent-runtime/
```

GitHub Pages deploys from `docs/`. The public documentation website is separate from local `arc ui`, previews, and `arc web` applications.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
