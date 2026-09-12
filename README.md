# ARC — Adaptive Agent Runtime

> **Reliable multi-agent orchestration and context control for long-horizon coding agents.**

[![CI](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-6b7280.svg)](LICENSE)
[![Website](https://img.shields.io/badge/site-GitHub%20Pages-88f7c5.svg)](https://anatwork14.github.io/adaptive-agent-runtime/)

<p align="center">
  <img src="docs/assets/hero_banner.jpg" alt="ARC Adaptive Agent Runtime Hero Banner" width="100%">
</p>

<p align="center">
  <strong><a href="https://anatwork14.github.io/adaptive-agent-runtime/">Interactive website</a></strong>
  · <strong><a href="docs/GETTING_STARTED.md">Getting started</a></strong>
  · <strong><a href="docs/ORCHESTRATION.md">Orchestration</a></strong>
  · <strong><a href="docs/OPERATOR_GUIDE.md">Operator guide</a></strong>
  · <strong><a href="docs/WEB_MISSION_CONTROL.md">Web Mission Control</a></strong>
</p>

ARC is a research-oriented runtime **and operator application** for coordinating coding agents without treating chat history, summaries, or vector memory as project truth.

The core rule is:

> **Adaptive memory is never authoritative.**

Authoritative project state lives in an append-only event stream plus Git state. Memory is a rebuildable, versioned projection used to compile the smallest useful context for each task.

**ARC 0.5 adds real multi-agent orchestration:** a replayable planner baseline, capability/cost/load-aware routing, concurrent isolated agent work, explicit file leases, and a serialized integration gate. CLI, TUI, browser UI, and WebSocket consumers all observe the same authoritative orchestration trace.

**Status:** experimental / pre-alpha. The orchestration substrate is functional and tested with the deterministic mock executor. Real Codex/Claude/Antigravity/OpenCode wrappers remain experimental; provider sandboxing, learned planning/routing, remote multi-user security, semantic retrieval, and repository-scale research evaluation remain active work.

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

Initialize a clean target repository and connect coding-agent accounts:

```bash
arc init . --project-id demo
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
arc auth status
arc agent doctor
```

ARC delegates sign-in to each provider's native account flow. Provider OAuth tokens remain in provider-owned credential/keyring stores; ARC only stores non-secret routing/profile metadata.

### Run one task

```bash
arc task create "Implement authentication middleware" \
  --file src/auth.py \
  --accept "tests pass"

arc route T001
arc run T001 --agent builder
```

### Run a multi-agent mission

```bash
arc mission plan "Add authentication with tests and docs" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --file docs/auth.md \
  --accept "tests pass" \
  --run
```

Or execute an existing READY frontier:

```bash
arc orchestrate
```

Open terminal Mission Control:

```bash
arc dashboard
```

Open browser Agent Orchestration Control:

```bash
arc web --open
```

Default browser address:

```text
http://127.0.0.1:8787
```

---

## ARC 0.5 orchestration

The correctness boundary is:

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
                            │
                            ▼
                    integration branch
```

### Planner baseline

`DeterministicPlanner` is intentionally simple and replayable, not presented as an LLM planner. Declared source surfaces become implementation work; test/docs surfaces become dependent tasks. Its output becomes normal authoritative tasks plus an `orchestration.plan_created` event.

That gives ARC a reproducible baseline before learned/LLM planning is introduced.

### Explainable routing

Agent profiles now carry:

```yaml
capabilities:
  - implementation
  - test
max_concurrency: 2
cost_weight: 1.0
quality_weight: 1.2
```

ARC routes using:

- required capabilities;
- task type / role match;
- provider readiness;
- per-agent concurrency load;
- quality and cost weights;
- routing policy (`balanced`, `quality`, `cost`).

Inspect a decision:

```bash
arc route T001 --policy quality
```

Tune a profile:

```bash
arc agent tune builder \
  --capability implementation \
  --capability test \
  --max-concurrency 2 \
  --quality-weight 1.3
```

The deterministic mock executor is **fallback-only** for automatic routing when an eligible real READY provider exists.

### Conflict control

Before dispatch ARC acquires exclusive leases for all declared files. Tasks with overlapping declared surfaces are not put in the same parallel batch. A conflicting task is deferred to a later round rather than becoming a second writer to the same surface.

### Event-visible decisions

Orchestration is observable and replayable:

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

See [docs/ORCHESTRATION.md](docs/ORCHESTRATION.md) for the full contract.

---

## Provider authentication and execution

| Provider | ARC provider | Native auth | Execution adapter |
|---|---|---|---|
| OpenAI Codex | `codex` | ChatGPT / OpenAI OAuth | 🧪 experimental |
| Claude Code | `claude` | Anthropic OAuth | 🧪 experimental |
| Google Antigravity | `antigravity` | Google OAuth / secure keyring | 🧪 experimental |
| OpenCode | `opencode` | CLI-managed | 🧪 experimental |
| OpenRouter | `openrouter` | environment gateway | gateway only |

Useful commands:

```bash
arc login
arc login codex --profile builder --default
arc auth status
arc agent doctor
```

ARC never copies provider credentials into `.arc/` or the browser UI.

Provider adapters never silently fall back to a mock success. ARC measures actual worktree changes and rejects empty/fabricated repository edits.

---

## Mission Control

### Terminal

```bash
arc dashboard
```

ARC 0.5 controls:

```text
a  route and run READY fleet
g  route and run selected READY task
y  retry selected failed/blocked task
x  cancel selected task
r  refresh
q  quit
```

The TUI shows task DAG state, provider readiness, routing metadata, recommended routes, budget/memory/lease state, and authoritative events.

### Browser

```bash
arc web --open
```

Browser Agent Orchestration Control provides:

- ARC Root + provider orchestrator cards;
- provider/profile readiness;
- provider-grouped running/idle teams;
- live task ledger;
- **Plan objective**;
- **Run ready** fleet orchestration;
- **Explain route**;
- ContextPacket inspection;
- budget/state/token/memory/lease telemetry;
- live authoritative WebSocket events;
- local API docs at `/api/docs`.

The browser does not simulate orchestration: the UI reacts to actual runtime events.

Relevant v0.5 APIs:

```text
POST /api/missions/plan
GET  /api/tasks/{task_id}/route
POST /api/orchestration/run
```

The browser has no remote-user authentication yet, so `arc web` is loopback-only by default. `--allow-remote` is an explicit network-boundary override, not an authentication mechanism.

---

## CLI surface

```text
arc init
arc login [PROVIDER]
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
arc web

arc mission plan
arc task create | list | show | run | retry | cancel
arc agent list | add | remove | doctor | tune
arc config show | default-agent
arc context build | inspect
arc memory list | why | consolidate | rebuild-index
arc gate inspect
```

---

## One application boundary

CLI, TUI, browser UI, and APIs share one service layer:

```text
                              ArcApplication
                                    │
                ┌───────────────────┼───────────────────┐
                │                   │                   │
             Planner              Router        task/context/memory
                │                   │                   │
                └──────────── OrchestrationEngine ─────┘
                                    │
                         concurrent agent phase
                                    │
                                    ▼
                              Orchestrator
                      explicit single integration writer
                                    │
                       event state + Git integration
```

The UI does not own a separate task database, routing state, or memory representation.

---

## Runtime architecture and correctness

ARC separates authoritative truth from adaptive context optimization:

```text
AUTHORITATIVE STATE                    ADAPTIVE MEMORY
append-only events                     derived projection
task DAG + routing trace               provenance
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
                isolated agent worktree
                          │
                          ▼
                  candidate commit
                          │
                          ▼
              serialized integration gate
```

If deleting ARC's derived memory/indexes would erase what **actually happened**, that information was stored in the wrong place.

The integration gate verifies the exact candidate in a fresh worktree and integrates that same candidate only after verification succeeds.

During concurrent orchestration, accepted-task memory processing is task-scoped so one worker's event stream cannot accidentally materialize another worker's reasoning into durable memory.

---

## Current implementation status

| Component | Status |
|---|---|
| SQLite WAL authoritative event store | ✅ implemented |
| Deterministic project/task replay | ✅ implemented |
| Shared `ArcApplication` service layer | ✅ implemented |
| Deterministic mission planner baseline | ✅ implemented |
| Capability/cost/load-aware router | ✅ implemented |
| Concurrent independent agent execution | ✅ implemented |
| Explicit serialized integration lock | ✅ implemented |
| All-declared-file leases + fencing | ✅ implemented |
| Overlap deferral across orchestration batches | ✅ implemented |
| Replayable orchestration decision events | ✅ implemented |
| CLI `mission plan` / `route` / `orchestrate` | ✅ implemented |
| TUI fleet orchestration | ✅ implemented |
| Browser plan/run/route controls | ✅ implemented |
| Native provider login orchestration | ✅ implemented |
| Auth-aware agent doctor | ✅ implemented |
| Codex / Claude / Antigravity / OpenCode execution adapters | 🧪 experimental |
| Versioned memory + provenance | ✅ implemented |
| Hard-budget context compiler | ✅ implemented |
| Real repository code evidence + hashes | ✅ implemented |
| Git worktree task isolation | ✅ implemented |
| Transactional exact-candidate integration gate | ✅ implemented |
| Docker-backed command/test sandbox | ✅ implemented |
| LLM/learned planner | 🚧 future research |
| Learned/bandit routing | 🚧 future research |
| Dynamic rate-limit/provider-latency scheduling | 🚧 future work |
| Provider CLI credential/container boundary | 🚧 not complete |
| Browser authentication / remote multi-user mode | 🚧 not complete |
| Real semantic embedding provider | 🚧 not complete |
| OpenRouter tool-using coding loop | 🚧 not complete |
| Repository-scale iso-cost orchestration benchmark | 🚧 not complete |

---

## Repository structure

```text
adaptive-agent-runtime/
├── application/    # app boundary, planner, router, orchestration, auth/config/events
├── adapters/       # Codex/Claude/Antigravity/OpenCode + deterministic Mock
├── cli/            # Typer operator CLI
├── tui/            # Textual Mission Control + login picker
├── webui/          # FastAPI + browser Agent Orchestration Control
├── context/        # retrieval, allocation, compiler, staleness
├── memory/         # lifecycle, provenance, supersession, consolidation
├── runtime/        # orchestrator, gate, leases, recovery, replay, budgets
├── state/          # authoritative event store + deterministic projections
├── isolation/      # Git worktrees and execution boundaries
├── verification/   # checks, reviewer, test runner
├── indexes/        # FTS, deterministic vector baseline, symbols, relations
├── eval/           # baselines, faults, grading, statistics
├── tests/
└── docs/
```

---

## Research framing

ARC now supports two related falsifiable questions:

> Can versioned, provenance-aware context control improve long-horizon coding reliability or reduce cost relative to transcript/static/vector-memory handoff at matched cost?

and:

> Can adaptive task decomposition/routing/scheduling improve resolved rate, latency, or cost over deterministic orchestration policies without weakening integration correctness?

ARC 0.5 deliberately records deterministic planner/router baselines so future LLM, contextual-bandit, or learned policies can be evaluated against stable controls.

Primary evaluation targets include:

```text
resolved rate @ iso-cost
end-to-end makespan
provider/task routing regret
tokens + USD per resolved task
retry / rejection rate
context staleness
handoff degradation
```

---

## CI and testing

The CI matrix runs on Python 3.11 and 3.12 and checks:

- install/build of the packaged application;
- correctness-focused Ruff rules;
- public-homepage and all Mission Control JavaScript syntax;
- full pytest suite;
- real Git worktree/candidate/gate integration using the deterministic mock;
- dependency-round orchestration;
- independent same-batch execution;
- overlapping-surface deferral;
- route/planner policy behavior;
- CLI/TUI/Web orchestration surfaces;
- provider auth probes without real secrets;
- FastAPI/WebSocket flows;
- localhost web safety behavior.

Run locally:

```bash
python -m pytest -q
python -m build
```

---

## Security

ARC executes code produced by AI agents. Treat that as untrusted-code execution.

Provider credentials remain in provider-owned credential stores and secure keyrings. ARC does not copy those tokens into `.arc/` or the browser UI.

The command/test execution path can use Docker isolation with network disabled, dropped capabilities, resource limits, and a read-only root filesystem. Provider coding CLIs are still experimental host-mode because safely brokering provider authentication into isolated containers requires additional design.

`arc web` is a local developer control surface, not an authenticated multi-user service. Keep the default loopback binding unless you put an appropriate trusted security boundary in front of it.

---

## Public website

Interactive project homepage:

```text
https://anatwork14.github.io/adaptive-agent-runtime/
```

GitHub Pages deploys from `docs/` using `.github/workflows/pages.yml`. This public documentation site is separate from the local `arc web` control plane.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
