# Reliable Context Control for Long-Horizon Multi-Agent Coding (`arc`)

> **Event-Sourced State, Versioned Adaptive Memory, and Risk-Aware Context Compilation**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-30%20passed-brightgreen.svg)]()

---

## 1. Architectural Foundation

Adaptive Agent Runtime (`arc`) rejects the common failure mode of treating lossy summaries or unbounded vector databases as authoritative shared memory.

Instead, `arc` enforces a strict separation of two planes:

```text
                  ┌──────────────────────────────────┐
                  │      AUTHORITATIVE STATE PLANE   │
                  │                                  │
                  │ append-only events (SQLite WAL)  │
                  │ task DAG + versions              │
                  │ git refs / patch hashes          │
                  │ leases + fencing tokens          │
                  │ test/gate outcomes               │
                  │ budgets                          │
                  │ artifact provenance              │
                  └───────────────┬──────────────────┘
                                  │
                       deterministic projections
                                  │
                                  ▼
                  ┌──────────────────────────────────┐
                  │         ADAPTIVE MEMORY PLANE    │
                  │                                  │
                  │ decisions                        │
                  │ assumptions                      │
                  │ failures                         │
                  │ procedures                       │
                  │ summaries                        │
                  │ code-surface memories            │
                  │ episodic traces                  │
                  │ lexical/vector/graph indexes     │
                  └───────────────┬──────────────────┘
                                  │
                           context compiler
                                  │
                                  ▼
                         per-agent context
```

### Core Invariant
> **Adaptive memory is never authoritative.**  
> Any memory object may be compressed, superseded, forgotten, re-ranked, or deleted without changing project correctness. The authoritative event log is always sufficient to reconstruct complete project state.

---

## 2. System Invariants

- **I1 — Single Authoritative Writer:** Only the orchestrator appends authoritative events. Agents submit requests to the orchestrator.
- **I2 — Event Log as Ground Truth:** The append-only SQLite WAL event log is the sole source of truth.
- **I3 — Derived Stores are Rebuildable:** Projections, FTS5 indexes, vector indexes, and memory relation graphs can be purged and rebuilt from the event stream.
- **I4 — Strict Memory Provenance:** Any memory without one or more source event IDs is rejected.
- **I5 — Temporal Validity:** Every memory has `valid_from_event`, optional `valid_to_event`, and `superseded_by`.
- **I6 — Worktree Isolation:** Agents work in isolated git worktrees or sandbox containers.
- **I7 — Serialized Integration Gate:** Patch integration is serialized through tiered verification stages (G0 Rebase/Staleness, G1 Syntax/Build, G2 Visible Tests, G3 Risk-Tiered Verification V0-V3).
- **I8 — Immutable Dispatched Context:** Dispatched contexts receive an immutable `context_id`, `state_version`, and canonical SHA-256 `digest`.
- **I9 — Context Reporting at Submission:** Every patch submission reports the context ID and state version under which it was generated.
- **I10 — Hidden-Test Isolation:** Grading suites and hidden tests are never exposed to agent execution environments.

---

## 3. Repository Structure

```text
adaptive-agent-runtime/
├── README.md
├── pyproject.toml
├── configs/
│   ├── dev.yaml
│   ├── eval.yaml
│   └── policies/
│       ├── default_policy.yaml
│       └── risk_policy.yaml
├── runtime/
│   ├── orchestrator.py    # Single-writer orchestrator
│   ├── scheduler.py       # Dependency-aware task scheduler
│   ├── budgets.py         # Financial and token budget accountant
│   ├── leases.py          # Optimistic leasing and fencing tokens
│   ├── gate.py            # Serialized integration gate (G0-G3 / V0-V3)
│   ├── recovery.py        # Automated fault recovery workflows
│   └── replay.py          # Deterministic event log replay engine
├── state/
│   ├── events.py          # SQLite WAL append-only event store
│   ├── projection.py      # Deterministic state projectors
│   ├── models.py          # Pydantic models for authoritative state
│   ├── schema.sql         # SQL schema definition
│   └── hashing.py         # Canonical JSON and SHA-256 hashing
├── memory/
│   ├── models.py          # Typed memory models
│   ├── candidates.py      # Deterministic candidate extraction triggers
│   ├── lifecycle.py       # Memory persistence & coordinator
│   ├── write_gate.py      # Scoring heuristic write gate
│   ├── provenance.py      # Provenance verification (I4, I5)
│   ├── conflicts.py       # Conflict classes (T0-T3) & supersession
│   ├── consolidation.py   # Failure and procedure consolidation
│   ├── forgetting.py      # Controlled archival and keep-scoring
│   └── feedback.py        # Operational utility feedback store
├── indexes/
│   ├── lexical.py         # SQLite FTS5 full-text index
│   ├── vector.py          # Local cosine similarity vector index
│   ├── symbols.py         # AST code symbol extraction and lookup
│   └── relations.py       # Memory relation graph index
├── context/
│   ├── request.py         # ContextRequest specification
│   ├── retrieval.py       # Ordered strategy retrieval router
│   ├── ranking.py         # Multi-criteria candidate scoring
│   ├── allocator.py       # Class token budget allocator (C0-C6)
│   ├── compiler.py        # ContextCompiler & immutable ContextPacket
│   ├── staleness.py       # State-version staleness detector
│   └── digest.py          # Canonical SHA-256 context packet digest
├── isolation/
│   ├── worktree.py        # Git worktree manager
│   ├── container.py       # Subprocess / sandbox container runner
│   └── checkpoints.py     # Checkpoint manager for rollback
├── adapters/
│   ├── base.py            # AgentAdapter protocol & AgentRunResult
│   ├── codex.py           # Codex / GPT-4o adapter
│   ├── claude.py          # Anthropic Claude adapter
│   ├── opencode.py        # Open-weights / local model adapter
│   └── openrouter.py      # OpenRouter API adapter
├── verification/
│   ├── static.py          # Syntax and static checks
│   ├── reviewer.py        # Automated security boundary reviewer
│   └── adversarial_tests.py # Test suite runner
├── eval/
│   ├── faults/injector.py # Memory fault injector (STALE_STATE, etc.)
│   ├── grading/hidden_tests.py # Isolated grading runner
│   ├── baselines/         # Baselines B0, B2, B3, B5, B7
│   ├── runners/           # Benchmark experiment runner
│   └── analysis/          # Bootstrap confidence intervals & statistics
├── cli/
│   └── main.py            # Typer CLI ('arc')
└── tests/
    ├── unit/              # 18 unit tests
    ├── integration/       # 6 integration tests (IT1-IT6)
    └── end_to_end/        # Full pipeline test
```

---

## 4. CLI Quickstart (`arc`)

The system provides the `arc` command-line utility:

### Initialize Project
```bash
arc init . --project-id my_project
```

### View Project Status, Task DAG, and Budget
```bash
arc status
```

### View Authoritative Events
```bash
arc events --limit 20
```

### Compile Context for a Task
```bash
arc context build task_1 --agent codex
```

### Inspect Memory Provenance ("Killer Debugging Feature")
```bash
arc memory why M_DEC_1
```
Output:
```text
──────────────── Memory Provenance: M_DEC_1 ────────────────
Type: decision
Status: active
Derived from Events: [12]
Valid Interval: Event 12 -> current
Content:
  Decision: All auth APIs return Result[T], not tuples
Access Count: 3
```

### Replay Event History from Scratch
```bash
arc replay
```

### Consolidate Recurring Failures
```bash
arc memory consolidate
```

### Rebuild Derived Indexes from Events
```bash
arc memory rebuild-index
```

---

## 5. Verification and Testing

Run the full automated test suite:
```bash
python -m pytest tests/ -v
```

### Test Coverage Highlights:
- **Unit Tests (`tests/unit/`):**
  - Event store monotonicity, content hashing, payload validation
  - Deterministic state projections, task DAG scheduling, leases, budgets
  - Memory provenance enforcement (I4/I5), conflict detection (T0-T3)
  - Lexical FTS5 search, vector embeddings, AST symbol lookups
  - Context compiler budget compliance (AC4), digest stability, staleness detection (AC6)
  - Typer CLI command invocations
- **Integration Tests (`tests/integration/`):**
  - **IT1 Cold Handoff:** Complete task transfer without transcript history
  - **IT2 Superseded API:** Guaranteeing superseded facts are excluded (AC3)
  - **IT3 Concurrent Dependency Change:** Detecting concurrent state drift
  - **IT4 Failed Attempt Memory:** Generating and delivering failure recovery knowledge
  - **IT5 Deterministic Replay:** Rebuilding complete state from scratch after index wipe (AC1, AC2)
  - **IT6 Memory Archival:** Archiving low-value memories while preserving critical decisions
- **End-to-End Tests (`tests/end_to_end/`):**
  - Multi-agent pipeline with heterogeneous agents (Codex + Claude), fault injection, and benchmark experiment aggregation.

---

## 6. Research Baselines

- **B0:** Single agent, full uninterrupted session.
- **B2:** Static multi-agent transcript handoff.
- **B3:** Static structured handoff without long-term memory (key baseline).
- **B5:** Standard vector top-k memory (unversioned).
- **B7:** Full proposed runtime (`arc`) with versioned adaptive memory and serialized integration gate.
