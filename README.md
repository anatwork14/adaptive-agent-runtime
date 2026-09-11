# ARC — Adaptive Agent Runtime

> **Reliable context control and Mission Control for long-horizon coding agents.**

[![CI](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/anatwork14/adaptive-agent-runtime/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-6b7280.svg)](LICENSE)
[![Website](https://img.shields.io/badge/site-GitHub%20Pages-88f7c5.svg)](https://anatwork14.github.io/adaptive-agent-runtime/)

<p align="center">
  <img src="docs/assets/hero_banner.jpg" alt="ARC Adaptive Agent Runtime Hero Banner" width="100%">
</p>

<p align="center">
  <strong><a href="https://anatwork14.github.io/adaptive-agent-runtime/">Interactive website</a></strong>
  ·
  <strong><a href="docs/GETTING_STARTED.md">Getting started</a></strong>
  ·
  <strong><a href="docs/OPERATOR_GUIDE.md">Operator guide</a></strong>
  ·
  <strong><a href="docs/WEB_MISSION_CONTROL.md">Web Mission Control</a></strong>
</p>

ARC is a research-oriented runtime **and operator application** for coordinating coding agents without treating chat history, summaries, or vector memory as project truth.

The core rule is:

> **Adaptive memory is never authoritative.**

Authoritative project state lives in an append-only event stream plus Git state. Memory is a rebuildable, versioned projection used to compile the smallest useful context for each task.

ARC exposes that runtime through four synchronized operator surfaces: the Typer CLI, live `arc watch`, a Textual terminal Mission Control, and a localhost browser Mission Control powered by FastAPI + WebSocket events.

**Status:** experimental / pre-alpha. The control-plane substrate, CLI v2, deterministic mock execution, transactional Git integration, terminal dashboard, and localhost browser control plane are implemented. Real provider wrappers, semantic retrieval, stronger provider sandboxing, remote authentication/authorization, and repository-scale research evaluation remain active work.

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

Then, from a clean Git repository that ARC should operate on:

```bash
arc init . --project-id demo
arc agent doctor

arc task create "Create a traceable ARC demo artifact" \
  --file arc_demo.txt \
  --accept "artifact integrates through the gate" \
  --risk 0.2

arc run T001 --agent mock
arc task show T001
arc events
```

The built-in `mock` profile is a deterministic zero-credential agent used to validate the **real ARC execution path** without provider costs. It writes a real repository change which must still survive worktree isolation, candidate commit creation, verification, and the integration gate.

Open terminal Mission Control:

```bash
arc dashboard
```

Open browser Mission Control:

```bash
arc web --open
```

Default browser address:

```text
http://127.0.0.1:8787
```

Or monitor a single mission:

```bash
arc watch T001
```

---

## Mission Control

### Terminal Mission Control

`arc dashboard` is a Textual TUI built on the same application layer as the CLI.

```text
┌──────────────────────── ARC Mission Control ─────────────────────┐
│ TASK DAG                              │ AGENTS / SYSTEM           │
│ T001  auth middleware   READY         │ ● builder   READY         │
│ T002  auth tests        CREATED       │ ○ reviewer  READY         │
├───────────────────────────────────────┼───────────────────────────┤
│ TASK DETAIL                           │ AUTHORITATIVE EVENTS       │
│ goal / agent / risk / files / history │ #42 task.created          │
│                                       │ #43 task.dispatched       │
│                                       │ #44 context.compiled      │
└───────────────────────────────────────┴───────────────────────────┘

[g] run   [y] retry   [x] cancel   [r] refresh   [q] quit
```

### Browser Mission Control

`arc web` launches a localhost-first FastAPI control plane and responsive browser UI over the same `ArcApplication`.

It provides:

- task DAG and mission detail;
- named agent readiness / doctor state;
- budget, state-version, memory, and lease telemetry;
- task create/run/retry/cancel controls;
- ContextPacket inspection;
- live authoritative events over WebSocket;
- local API docs at `/api/docs`.

The browser currently has **no built-in authentication**, so ARC binds to `127.0.0.1` by default and refuses non-loopback exposure unless `--allow-remote` is explicitly supplied. `--allow-remote` is an opt-in safety override, not an authentication mechanism.

See [docs/WEB_MISSION_CONTROL.md](docs/WEB_MISSION_CONTROL.md).

There is no separate TUI/Web project database and no duplicated execution logic.

---

## CLI v2

The main operator surface is:

```text
arc init
arc status
arc events
arc replay
arc run TASK
arc watch TASK
arc dashboard
arc web

arc task create | list | show | run | retry | cancel
arc agent list | add | remove | doctor
arc config show | default-agent
arc context build | inspect
arc memory list | why | consolidate | rebuild-index
arc gate inspect
```

Example named Codex profile:

```bash
arc agent add builder \
  --provider codex \
  --role implementation \
  --default

arc agent doctor builder
arc run T001 --agent builder
```

Provider-named adapters never silently fall back to a mock success:

- `CodexAgentAdapter` invokes a real Codex CLI or fails;
- `ClaudeAgentAdapter` invokes a real Claude CLI or fails;
- `OpenCodeAgentAdapter` invokes a real OpenCode CLI or fails;
- OpenRouter remains gateway-only until ARC has a real filesystem tool loop for it.

Provider command overrides remain available:

```bash
export ARC_CODEX_COMMAND='codex exec --full-auto -'
export ARC_CLAUDE_COMMAND='claude -p'
export ARC_OPENCODE_COMMAND='opencode run'
```

See [docs/OPERATOR_GUIDE.md](docs/OPERATOR_GUIDE.md) for the full command/config reference.

---

## One application boundary

CLI, TUI, browser UI, and future APIs share one service layer:

```text
                           ArcApplication
                                  │
          ┌───────────────┬───────┼────────┬───────────────┐
          │               │       │        │               │
       Typer CLI       arc watch  Textual  FastAPI      future API
                                  TUI      + WebSocket
          │               │       │        │               │
          └───────────────┴───────┼────────┴───────────────┘
                                  ▼
                             Orchestrator
                           single execution writer
                                  │
                    event state + Git integration
```

`ArcApplication` centralizes task lifecycle, agent/profile resolution, context inspection, project snapshots, and live event access. The existing `Orchestrator` remains the single authoritative execution writer.

The browser server adds a single execution lock for web-triggered runs so one server instance does not launch competing integration mutations from two simultaneous button presses.

---

## Why ARC exists

Adding more coding agents creates new failure modes:

- Agent B receives stale assumptions from Agent A.
- Transcript handoff becomes expensive and noisy.
- Summaries silently lose constraints.
- Vector retrieval returns facts that were already superseded.
- Two agents duplicate the same exploration.
- A patch is verified against the wrong repository tree.
- Failed attempts disappear, so the next worker repeats them.

ARC treats these as **state, context, integration, and recovery problems**, not prompt-engineering problems.

<p align="center">
  <img src="docs/assets/comparison_diagram.jpg" alt="Naive Vector Memory vs ARC Deterministic State Plane" width="100%">
</p>

---

## Runtime architecture

<p align="center">
  <img src="docs/assets/architecture_diagram.jpg" alt="ARC Two-Plane Architecture: Authoritative State vs Adaptive Memory" width="100%">
</p>

```text
                              USER / TASK SPEC
                                     │
                                     ▼
                              versioned Task DAG
                                     │
                                     ▼
                    ┌─────────────────────────────┐
                    │ ORCHESTRATOR — single writer│
                    └──────────────┬──────────────┘
                                   │
                  ┌────────────────┴────────────────┐
                  ▼                                 ▼
       AUTHORITATIVE STATE                 ADAPTIVE MEMORY
       append-only events                  derived projection
       task/version state                  provenance
       leases + budgets                    validity intervals
       candidate commits                   supersession
       gate outcomes                       failure/procedure memory
                  │                                 │
                  └────────────────┬────────────────┘
                                   ▼
                           CONTEXT COMPILER
                     hard budget + real code evidence
                                   │
                                   ▼
                        immutable ContextPacket
                                   │
                                   ▼
                       isolated agent worktree
                                   │
                                   ▼
                         candidate git commit
                                   │
                                   ▼
                    SERIALIZED INTEGRATION GATE
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                       reject             accept
                                             │
                                             ▼
                                  integration branch
```

### Correctness boundary

If deleting ARC's memory database/indexes would make you lose what **actually happened**, that information was stored in the wrong place.

The event log must be sufficient to reconstruct authoritative project state. Derived memory can be rebuilt from recorded `memory.materialized` events without re-running a summarizer or model.

---

## Transactional integration

Agent changes are materialized as an immutable candidate commit. The gate verifies that exact candidate in a fresh worktree before integrating that same commit.

<p align="center">
  <img src="docs/assets/gate_pipeline.jpg" alt="ARC Serialized Integration Gate" width="100%">
</p>

```text
candidate commit
      ↓
fresh gate worktree at current integration HEAD
      ↓
cherry-pick candidate
      ↓
static checks / configured tests / optional review
      ↓
PASS → cherry-pick same candidate into integration
FAIL → discard candidate integration attempt
```

ARC keeps `.arc/` out of Git status through the repository-local `.git/info/exclude`, so runtime metadata does not violate the gate's clean-tree invariant and no committed `.gitignore` edit is required.

---

## Current implementation status

| Component | Status |
|---|---|
| SQLite WAL authoritative event store | ✅ implemented |
| Deterministic project/task replay | ✅ implemented |
| Shared `ArcApplication` service layer | ✅ implemented |
| CLI v2 task lifecycle | ✅ implemented |
| Named agent profiles + `agent doctor` | ✅ implemented |
| Live `arc watch` | ✅ implemented |
| Textual `arc dashboard` Mission Control | ✅ implemented |
| FastAPI `arc web` browser Mission Control | ✅ implemented |
| WebSocket authoritative event stream | ✅ implemented |
| Versioned memory + provenance | ✅ implemented |
| Memory materialization replay path | ✅ implemented |
| Hard-budget context compiler | ✅ implemented |
| Real repository code evidence + hashes | ✅ implemented |
| Git worktree task isolation | ✅ implemented |
| Immutable candidate commit | ✅ implemented |
| Transactional integration gate | ✅ implemented |
| Explicit mock test adapter | ✅ implemented |
| Docker-backed command/test sandbox | ✅ implemented |
| Codex / Claude / OpenCode CLI wrappers | 🧪 experimental |
| Provider CLI credential/container boundary | 🚧 not complete |
| Browser authentication / remote multi-user mode | 🚧 not complete |
| Real semantic embedding provider | 🚧 not complete |
| OpenRouter tool-using coding loop | 🚧 not complete |
| Repository-scale iso-cost benchmark | 🚧 not complete |
| Learned risk / memory policies | 🚧 research stage |

---

## Repository structure

```text
adaptive-agent-runtime/
├── application/    # shared app/service layer + config + agent resolution + events
├── adapters/       # provider CLI adapters + explicit MockAgentAdapter
├── cli/            # Typer CLI v2 + installed UI-aware entrypoint
├── tui/            # Textual terminal Mission Control
├── webui/          # FastAPI + packaged localhost browser Mission Control
├── context/        # retrieval, ranking, allocation, compiler, staleness
├── memory/         # lifecycle, provenance, supersession, consolidation
├── runtime/        # orchestrator, gate, leases, recovery, replay, budgets
├── state/          # authoritative event store + deterministic projections
├── isolation/      # git worktrees and execution boundaries
├── verification/   # static checks, reviewer, test runner
├── indexes/        # FTS, deterministic vector baseline, symbols, relations
├── eval/           # baselines, faults, grading, statistics
├── tests/
├── docs/           # public website + operator documentation
└── final_adaptive_memory_context_runtime.md
```

---

## Research framing

ARC asks a falsifiable question:

> Can versioned, provenance-aware context control improve long-horizon coding reliability or reduce cost relative to transcript handoff, static structured handoff, and ordinary vector top-k memory **at matched cost**?

Planned comparisons include single-agent, static structured handoff, transcript handoff, rolling summary, vector top-k, event-sourced static memory, and the full ARC runtime.

Primary outcome:

```text
resolved rate @ iso-cost
```

with hidden tests, regression checks, context-pressure strata, and paired task analysis. A negative result can still identify the crossover point where multi-agent/context machinery stops paying for itself.

---

## CI and testing

The CI matrix runs on Python 3.11 and 3.12 and checks:

- install/build of the packaged application;
- correctness-focused Ruff rules;
- public-homepage and Web Mission Control JavaScript syntax;
- the full pytest suite;
- real Git worktree/candidate/gate integration with `MockAgentAdapter`;
- CLI v2 lifecycle/profile flows;
- authoritative retry/cancel semantics;
- headless Textual dashboard startup;
- FastAPI snapshot/task/context/run flows;
- WebSocket authoritative event streaming;
- packaged Web UI static serving;
- localhost-only web safety behavior.

Run locally:

```bash
python -m pytest -q
python -m build
```

---

## Security

ARC executes code produced by AI agents. Treat that as untrusted-code execution.

The command/test execution path can use Docker isolation with network disabled, dropped capabilities, resource limits, and a read-only root filesystem. Provider coding CLIs are still experimental host-mode because safely brokering provider authentication into isolated containers requires additional design.

`arc web` is a local developer control surface, not an authenticated multi-user service. Keep the default loopback binding unless you put an appropriate trusted security boundary in front of it.

Use disposable repositories/environments for experimental provider runs and do not expose valuable host credentials to untrusted generated code.

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
