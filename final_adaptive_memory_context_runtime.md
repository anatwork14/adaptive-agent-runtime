# Reliable Context Control for Long-Horizon Multi-Agent Coding
## Event-Sourced State, Versioned Adaptive Memory, and Risk-Aware Context Compilation

**Version:** 1.0 — Implementation-Ready Specification  
**Status:** Final synthesis of the reviewed Reliable Multi-Agent Coding Runtime and Adaptive Memory & Context Lifecycle directions  
**Research target:** undergraduate thesis / systems + agents paper / open-source runtime  
**Implementation target:** Python 3.11+, Linux/Docker, local or API-backed coding agents  
**Recommended development style:** build deterministic substrate first; learned policies only after the substrate produces replayable traces

---

# 0. Executive Decision

This project should **not** be implemented as:

```text
multi-agent runtime
        +
generic vector memory
        +
summarizer
```

That architecture makes memory another loosely coupled feature and creates a dangerous failure mode: a lossy memory summary can silently become the shared "truth" for every agent.

The final architecture instead has **two explicitly separated planes**:

```text
                  ┌──────────────────────────────────┐
                  │      AUTHORITATIVE STATE PLANE   │
                  │                                  │
                  │ append-only events               │
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

## Core invariant

> **Adaptive memory is never authoritative.**

A memory object may be compressed, superseded, forgotten, re-ranked, or deleted without changing project correctness.

The authoritative event log must always be sufficient to reconstruct:
- project state;
- task state;
- decisions that were committed;
- patch/gate outcomes;
- ownership/fencing state;
- cost history;
- memory provenance.

This separation is the central architectural choice of this specification.

---

# 1. Final Research Thesis

The project asks:

> **Can state-aware adaptive context management make long-horizon multi-agent coding more reliable and cost-efficient than static handoff or full-history approaches, without allowing lossy memory to compromise correctness?**

The research contribution is **not** simply:
- multi-agent coding;
- event sourcing;
- vector memory;
- adaptive retrieval;
- choosing different memory structures;
- a learned write gate.

All of those ideas exist independently.

The contribution is the composition and evaluation of a **reliability-aware context control plane** in which:

1. authoritative project state is event-sourced and versioned;
2. memory is a non-authoritative derived projection;
3. every memory object carries provenance and validity boundaries;
4. stale/superseded memories can be detected structurally;
5. a context compiler allocates a finite token budget across authoritative state, repository evidence, decisions, assumptions, failures, and procedures;
6. retrieval depends on task state, dependency structure, project version, agent role, risk, and budget;
7. context handoff across heterogeneous agents is explicitly measured;
8. evaluation is performed on repository-scale tasks with hidden tests and iso-cost comparisons;
9. execution traces are replayable.

---

# 2. Why the Two Original Directions Should Be Combined

The reviewed multi-agent runtime already requires:
- structured handoff packets;
- a versioned event store;
- agent isolation;
- a single-writer integration gate;
- task DAG state;
- replayable execution;
- recovery;
- budget accounting.

The adaptive-memory project independently requires:
- memory creation;
- representation choice;
- retrieval;
- consolidation;
- conflict handling;
- compression;
- forgetting.

These are not separate systems.

The handoff packet is exactly the point where **memory becomes execution context**.

The final relationship is:

```text
event stream
    │
    ├──► deterministic project projections
    │
    └──► memory lifecycle
              │
              ▼
        adaptive retrieval
              │
              ▼
        context compiler
              │
              ▼
       structured handoff
              │
              ▼
           agent
```

Therefore:

> The multi-agent runtime provides the **ground truth and execution substrate**.  
> Adaptive memory provides the **context-control layer**.

This makes the combined project substantially stronger than either direction alone.

---

# 3. Current Novelty Boundary — Do Not Overclaim

As of September 2026, several nearby ideas already exist.

## 3.1 Gated-Memory Routing

Recent work learns a memory write gate and retrieval gate for multi-agent collaboration and uses the resulting compact execution memory to guide role/model routing.

Therefore, **"learn what to retain for multi-agent routing" is not sufficient novelty**.

Our differentiation:

- repository-scale software engineering rather than mainly reasoning/code-generation benchmarks;
- authoritative vs derived state separation;
- explicit `state_version`;
- source-event provenance;
- stale-memory detection;
- supersession semantics;
- integration with task DAG, worktrees, gate and recovery;
- hidden-test end-to-end outcomes;
- context-loss and stale-context failure measurement;
- replayable engineering traces.

## 3.2 FluxMem / Adaptive Memory Structures

Adaptive selection between memory structures has already been studied.

Therefore:

> **"choose vector vs graph vs summary dynamically" must not be the headline contribution.**

Representation selection is an internal mechanism only.

## 3.3 ESAA-Conversational / Event-Sourced Shared Memory

Event-sourced continuity and handoff across heterogeneous coding agents has also been proposed.

Therefore:

> **"shared event-sourced memory between Codex and Claude" is not enough.**

Our system governs the coding execution itself:
- tasks;
- versions;
- patches;
- repository state;
- tests;
- integration;
- risk;
- context assembly;
- recovery.

## 3.4 ContextBench

Context retrieval for coding agents remains weak even when sophisticated scaffolding is used. A key observed issue is the gap between context that agents explore and context they actually use.

This motivates measuring **delivered context quality**, not just final task success.

## 3.5 Memory Benchmarks

Recent long-horizon memory benchmarks show:
- interference from updated facts remains difficult;
- retrieval/construction is a major bottleneck;
- memory should be evaluated inside agentic tasks rather than only static recall.

This directly motivates versioned/superseding project memory.

---

# 4. Research Questions and Falsifiable Hypotheses

All comparisons must be:
- paired per task where possible;
- iso-dollar as the primary comparison;
- additionally reported at iso-wall-clock;
- model/version/prices pinned by date.

---

## H0 — Memory/control null

**Null hypothesis:**

> At equal dollar cost, the proposed adaptive context-control runtime does not improve end-to-end resolved rate over a strong static structured-handoff baseline.

**Primary metric:**
- resolved rate @ iso-cost.

**Project-level falsification condition:**
- if adaptive memory/context does not improve reliability or reduce cost on any long-horizon/context-pressure stratum, the project must be reframed as a characterization/negative-result study.

---

## H1 — Structured projection vs transcript

**Hypothesis:**

> Versioned structured context achieves equivalent or better task success than transcript-based handoff while delivering fewer tokens.

**Metrics:**
- resolved rate;
- delivered context tokens;
- cold-agent startup cost;
- context precision/recall where gold context exists.

**Falsified if:**
- task success falls beyond a preregistered equivalence margin.

---

## H2 — Versioning and supersession

**Hypothesis:**

> Memory objects with explicit provenance, validity intervals, and supersession reduce stale-context errors compared with ordinary recency/vector memory.

**Metrics:**
- stale-memory retrieval rate;
- stale-context-caused gate rejection;
- update-interference accuracy;
- time-to-correct-context after a state change.

**Falsified if:**
- no statistically meaningful reduction in stale-context errors.

---

## H3 — Adaptive context compilation

**Hypothesis:**

> Risk-aware budget allocation across context classes outperforms fixed top-k retrieval and fixed token partitions at equal delivered-token budget.

**Metrics:**
- hidden-test pass;
- context utilization;
- context precision;
- cost.

**Falsified if:**
- oracle-tuned fixed policy matches or beats adaptive policy.

---

## H4 — Cross-agent continuity

**Hypothesis:**

> Structured context reconstruction reduces the cost and performance degradation caused by agent handoff.

**Metrics:**
- handoff recovery latency;
- first-action correctness after handoff;
- repeated-tool-call ratio;
- re-exploration tokens;
- task success.

---

## H5 — Lifecycle management

**Hypothesis:**

> Consolidation and controlled forgetting reduce memory-management cost without reducing project success.

**Metrics:**
- index size;
- retrieval latency;
- delivered tokens;
- resolved rate;
- stale-memory rate.

---

## H6 — Memory-aware reliability

**Hypothesis:**

> Memory-derived signals improve prediction of gate rejection and therefore enable more efficient verification/context allocation.

Candidate features:
- context age;
- superseded-memory ratio;
- unresolved assumption count;
- state-version lag;
- declared-vs-touched divergence;
- retrieval disagreement;
- prior failure density.

Standalone result:

> Can we predict when an agent is likely to fail because its context is stale, incomplete, or contradictory?

This remains publishable even if the adaptive policy itself does not win.

---

# 5. Non-Goals

Do not attempt to solve all of the following in v1:

- general human-like autobiographical memory;
- arbitrary personal-assistant memory;
- reinforcement learning from scratch;
- neural end-to-end memory training;
- globally consistent distributed databases;
- semantic understanding of all possible code conflicts;
- perfect planning;
- persistent user profiling;
- GUI memory editing;
- cross-organization knowledge sharing.

The scope is:

> **Long-horizon software-engineering agents operating on one repository/project workspace.**

---

# 6. System Invariants

These are implementation requirements, not suggestions.

## I1 — Single authoritative writer

Only the orchestrator writes authoritative events.

Agents submit requests/events to the orchestrator.

## I2 — Event log is source of truth

No projection, summary, vector store, graph store, or handoff packet is authoritative.

## I3 — Derived stores must be rebuildable

The following are caches/projections:
- materialized state;
- FTS index;
- vector index;
- graph index;
- memory table projections.

Deleting them must not destroy project history.

## I4 — Every memory has provenance

A memory without one or more source event IDs is invalid for runtime use.

## I5 — Every memory has temporal validity

Memory must support:
- `valid_from_event`;
- optional `valid_to_event`;
- `superseded_by`;
- `status`.

## I6 — Agents cannot write shared repository state

Each agent works in an isolated worktree/container.

## I7 — Integration is serialized

Only the gate commits accepted work to the integration branch.

## I8 — Context is immutable per dispatch

A dispatched context packet receives:
- `context_id`;
- `state_version`;
- `digest`.

The agent cannot mutate that packet retroactively.

## I9 — Submission reports the dispatch context

Every patch submission contains:
- context ID used;
- dispatch state version;
- task ID;
- fencing token(s);
- agent ID.

## I10 — Hidden tests are never exposed

They exist only in the grading environment.

---

# 7. Final Architecture

```text
                              USER SPEC
                                  │
                                  ▼
                         ┌────────────────┐
                         │ Project Planner│
                         └───────┬────────┘
                                 │
                                 ▼
                         versioned Task DAG
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  ORCHESTRATOR — SINGLE WRITER                       │
│                                                                     │
│ admission | task scheduling | budgets | leases | risk | recovery   │
└──────────────┬─────────────────────────────┬────────────────────────┘
               │                             │
               │ append                      │ request context
               ▼                             ▼
      ┌─────────────────┐          ┌──────────────────────────┐
      │ AUTHORITATIVE   │          │  CONTEXT CONTROL PLANE   │
      │ EVENT STORE     │─────────►│                          │
      │                 │ project  │ memory lifecycle         │
      │ SQLite WAL      │ events   │ retrieval router         │
      │ append-only     │          │ context compiler         │
      └───────┬─────────┘          └────────────┬─────────────┘
              │                                 │
              │ projections                     │ immutable packet
              ▼                                 ▼
      ┌─────────────────┐          ┌──────────────────────────┐
      │ Project State   │          │ Agent Context Packet     │
      │ Task State      │          │ task + evidence + memory │
      │ Lease State     │          └────────────┬─────────────┘
      │ Budget State    │                       │
      └─────────────────┘                       ▼
                                  ┌─────────────────────────────┐
                                  │ Isolated Agent Container     │
                                  │ worktree + branch            │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                           patch submission
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │ SERIAL INTEGRATION GATE     │
                                  │ rebase                      │
                                  │ build/typecheck             │
                                  │ visible tests               │
                                  │ risk-selected verification  │
                                  └──────────────┬──────────────┘
                                         accept │ reject
                                                │
                         ┌──────────────────────┴────────────────────┐
                         ▼                                           ▼
                  commit + events                           recovery/replan
                         │                                           │
                         └───────────────────┬───────────────────────┘
                                             ▼
                                      new project state
                                             │
                                             └──► memory update
```

---

# 8. Authoritative State Plane

Use:

- SQLite;
- WAL mode;
- one writer process;
- append-only event table;
- deterministic projections.

## 8.1 Core event table

```sql
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    actor           TEXT NOT NULL,
    kind            TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    task_id         TEXT,
    payload         TEXT NOT NULL,
    causation_id    INTEGER,
    correlation_id  TEXT,
    fencing_token   INTEGER,
    content_hash    TEXT NOT NULL
);

CREATE INDEX idx_events_project_id
ON events(project_id, id);

CREATE INDEX idx_events_task_id
ON events(task_id, id);

CREATE INDEX idx_events_kind
ON events(kind, id);
```

## 8.2 Required event kinds

### Project

```text
project.created
project.spec_updated
project.constraint_added
project.constraint_removed
```

### Task

```text
task.created
task.updated
task.dispatched
task.blocked
task.submitted
task.split
task.merged
task.failed
task.abandoned
```

### Lease

```text
lease.requested
lease.granted
lease.renewed
lease.preempted
lease.released
lease.rejected
```

### Agent

```text
agent.started
agent.stopped
agent.killed
agent.handoff_requested
agent.handoff_completed
```

### Context

```text
context.requested
context.compiled
context.dispatched
context.invalidated
context.feedback
```

### Memory

```text
memory.created
memory.updated
memory.superseded
memory.archived
memory.deleted
memory.accessed
memory.conflict_detected
memory.conflict_resolved
```

### Gate

```text
gate.started
gate.c0_failed
gate.c1_failed
gate.c2_failed
gate.v2_failed
gate.v3_failed
gate.accepted
gate.rejected
```

### Recovery

```text
recovery.started
recovery.retry
recovery.reassign
recovery.split
recovery.restore
recovery.replan
recovery.escalate
```

### Budget

```text
budget.reserved
budget.consumed
budget.exhausted
```

---

# 9. Memory Plane — What Is Actually Stored

Memory is typed.

Do not store a generic list of embeddings and call it memory.

Required memory types:

| Type | Meaning | Example |
|---|---|---|
| `fact` | project fact that may evolve | API now returns `Result[T]` |
| `decision` | committed design choice | use event-sourced SQLite |
| `assumption` | unverified working belief | module X has no external callers |
| `procedure` | reusable execution procedure | how to run integration tests |
| `failure` | failed approach + evidence | migration failed because schema Y |
| `task_summary` | compressed finished/in-progress task state | auth refactor progress |
| `code_surface` | semantic pointer into repository | auth interfaces and call sites |
| `artifact` | reference to generated artifact | benchmark manifest |
| `episode` | compressed interaction/execution history | prior agent attempt |
| `constraint` | durable limit | no network in agent container |

---

# 10. Memory Representations

A memory type and a representation are different concepts.

Representations:

```text
RAW_EVENT_REFS
STRUCTURED_FACT
SUMMARY
DECISION_RECORD
PROCEDURE
CODE_POINTER
GRAPH_RELATION
EMBEDDED_CHUNK
ARTIFACT_POINTER
```

Example:

A `decision` memory may be represented as a `DECISION_RECORD`.

A `failure` memory may have:
- structured failure class;
- short summary;
- source-event references;
- embedding for semantic lookup.

Do not force every memory into one representation.

---

# 11. Memory Database Schema

```sql
CREATE TABLE memories (
    memory_id              TEXT PRIMARY KEY,
    project_id             TEXT NOT NULL,
    type                   TEXT NOT NULL,
    representation         TEXT NOT NULL,

    content_json           TEXT NOT NULL,
    content_text           TEXT,

    created_event          INTEGER NOT NULL,
    valid_from_event       INTEGER NOT NULL,
    valid_to_event         INTEGER,

    state_version_at_write INTEGER NOT NULL,

    status                 TEXT NOT NULL,

    superseded_by          TEXT,

    confidence             REAL NOT NULL,
    importance             REAL NOT NULL,
    predicted_reuse        REAL NOT NULL,

    access_count           INTEGER NOT NULL DEFAULT 0,
    last_accessed_event    INTEGER,

    token_size             INTEGER NOT NULL,
    content_hash           TEXT NOT NULL,

    producer_type          TEXT NOT NULL,

    producer_model         TEXT,
    producer_prompt_hash   TEXT
);
```

Status:

```text
active
superseded
archived
deleted
disputed
```

## 11.1 Provenance

```sql
CREATE TABLE memory_sources (
    memory_id       TEXT NOT NULL,
    source_event_id INTEGER NOT NULL,
    source_role     TEXT NOT NULL,
    PRIMARY KEY(memory_id, source_event_id)
);
```

Possible `source_role`:

```text
supports
caused_by
summarizes
supersedes
derived_from
validated_by
```

## 11.2 Relations

```sql
CREATE TABLE memory_relations (
    src_memory_id TEXT NOT NULL,
    relation      TEXT NOT NULL,
    dst_memory_id TEXT NOT NULL,
    created_event INTEGER NOT NULL,
    PRIMARY KEY(src_memory_id, relation, dst_memory_id)
);
```

Useful relations:

```text
supports
contradicts
depends_on
supersedes
implements
caused
related_to
```

## 11.3 Retrieval feedback

```sql
CREATE TABLE memory_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id       TEXT NOT NULL,
    context_id      TEXT NOT NULL,
    task_id         TEXT NOT NULL,

    delivered       INTEGER NOT NULL,
    used            INTEGER,
    useful          INTEGER,
    stale           INTEGER,
    misleading      INTEGER,

    downstream_gate TEXT,
    event_id        INTEGER NOT NULL
);
```

This table is required for later offline learning.

---

# 12. Derived Indexes

Use separate rebuildable indexes.

## Required

### FTS5

For:
- exact names;
- symbol names;
- errors;
- task terms;
- decisions.

### Vector index

Recommended MVP:
- `hnswlib` or equivalent local HNSW index;
- key = `memory_id`;
- embedding metadata remains in SQLite.

### Code index

Use:
- ripgrep;
- tree-sitter symbol extraction;
- import/call graph where available.

### Optional graph view

Do **not** require Neo4j.

Use SQLite relation tables first.

A dedicated graph database is only justified if profiling proves SQLite traversal inadequate.

---

# 13. The Memory Lifecycle

```text
authoritative event
      │
      ▼
candidate extraction
      │
      ▼
write gate
  ┌───┴─────┐
drop      retain
            │
            ▼
     classify memory type
            │
            ▼
   choose representation
            │
            ▼
  attach provenance/version
            │
            ▼
      conflict check
            │
            ▼
      store + index
            │
            ▼
  monitor utility / staleness
            │
     ┌──────┼────────┐
     ▼      ▼        ▼
   keep   merge   supersede
                   / archive
```

---

# 14. Candidate Extraction

Do not ask an LLM to summarize every event.

Candidate memory creation triggers:

## Deterministic triggers

Always create/update memory candidate for:
- accepted architectural decision;
- constraint change;
- gate rejection;
- recurring failure;
- task completion;
- procedure validated by successful run;
- artifact creation;
- assumption validation/invalidation;
- public API/signature change;
- dependency/config migration.

## Optional semantic triggers

Use a cheap model/classifier for:
- likely reusable insight;
- important rationale;
- non-obvious failure explanation;
- reusable repository convention.

---

# 15. Memory Write Gate

## Phase A — deterministic heuristic

Start with a frozen score:

```text
write_score =
    2.0 * durable_decision
  + 1.5 * dependency_reach
  + 1.5 * failure_recurrence_risk
  + 1.2 * expected_reuse
  + 1.0 * novelty
  + 0.8 * source_confidence
  - 1.2 * redundancy
  - 0.5 * storage_cost
```

Store if:

```text
write_score >= WRITE_THRESHOLD
```

The exact initial coefficients are engineering defaults, not scientific claims.

Do not tune them on the final test set.

## Phase B — offline learned gate

After sufficient traces:

Features:
- event kind;
- task type;
- DAG fanout;
- code surface;
- dependency depth;
- time since similar memory;
- source confidence;
- historical retrieval utility;
- token size;
- recurrence count.

Label candidates by downstream utility.

Recommended models:
- logistic regression;
- gradient-boosted trees.

Do not begin with RL.

---

# 16. Provenance and Validity

This is a core novelty mechanism.

Every memory object must answer:

```text
Where did this come from?
When did it become valid?
Is it still valid?
What replaced it?
Was it deterministic or generated by a model?
```

Example:

```json
{
  "memory_id": "M_API_17",
  "type": "fact",
  "content": {
    "subject": "AuthClient.login",
    "predicate": "return_type",
    "object": "Result[Token]"
  },
  "created_event": 4810,
  "valid_from_event": 4805,
  "valid_to_event": null,
  "state_version_at_write": 4810,
  "source_events": [4805, 4806],
  "status": "active",
  "superseded_by": null
}
```

Later:

```json
{
  "memory_id": "M_API_22",
  "content": {
    "subject": "AuthClient.login",
    "predicate": "return_type",
    "object": "AuthResult"
  },
  "valid_from_event": 5320
}
```

Then:

```text
M_API_17.valid_to_event = 5319
M_API_17.status = superseded
M_API_17.superseded_by = M_API_22
```

A normal vector store usually does not provide this guarantee.

---

# 17. Memory Conflict Detection

Conflict classes:

## T0 — exact-key update

Same structured subject + predicate, different value.

Deterministic.

## T1 — temporal supersession

Later project event intentionally replaces earlier fact/decision.

Resolve via event order + committed status.

## T2 — contradictory assumptions

Two active assumptions cannot both hold.

Mark:

```text
status = disputed
```

Do not silently choose.

## T3 — semantic conflict

Possible natural-language inconsistency.

Use:
- embedding candidate generation;
- LLM conflict judge.

This is best-effort only.

Do not claim complete semantic consistency.

---

# 18. Consolidation

Consolidation combines redundant memories while retaining provenance.

Example:

Three failures:

```text
pytest failed due missing postgres service
integration test failed because postgres unavailable
CI reproduction failed: postgres not started
```

May become:

```json
{
  "type": "procedure",
  "content": {
    "rule": "Integration tests require postgres service before pytest.",
    "validated_command": "docker compose up -d postgres"
  },
  "sources": ["M1", "M7", "M12"]
}
```

The original source events remain.

---

# 19. Forgetting

"Forget" means remove from active retrieval, not erase project history.

Actions:

```text
retain
compress
merge
archive
delete_derived_object
```

Never delete authoritative events.

Candidate keep score:

```text
keep_score =
    importance
  + predicted_reuse
  + access_utility
  + dependency_reach
  + source_confidence
  - staleness
  - redundancy
  - retrieval_cost
```

Hard-retain classes:
- current specification;
- active constraints;
- committed decisions affecting active DAG nodes;
- unresolved failures;
- unresolved assumptions;
- current API/interface facts;
- security boundaries.

---

# 20. Retrieval Request Schema

```json
{
  "context_request_id": "CR_29",
  "project_id": "P1",
  "task_id": "T17",
  "agent_id": "codex_2",

  "state_version": 5821,

  "goal": "...",
  "task_type": "refactor",
  "risk": 0.72,

  "files_declared": [
    "src/auth/**"
  ],

  "symbols": [
    "AuthClient",
    "login"
  ],

  "dependencies": [
    "T12"
  ],

  "token_budget": 24000,

  "agent_context_limit": 128000,

  "requested_classes": [
    "decision",
    "assumption",
    "failure",
    "procedure",
    "code_surface"
  ]
}
```

---

# 21. Retrieval Router

The router chooses retrieval strategies, not just top-k.

Available retrievers:

```text
AUTHORITATIVE_LOOKUP
TASK_DEPENDENCY_LOOKUP
EXACT_SYMBOL
LEXICAL_FTS
VECTOR
RELATION_GRAPH
RECENCY
FAILURE_HISTORY
PROCEDURE_LOOKUP
```

Default ordering for coding tasks:

```text
1. authoritative task/spec lookup
2. active decisions/constraints
3. exact code/symbol lookup
4. dependency-linked memory
5. failures/procedures
6. lexical retrieval
7. vector retrieval
```

Vector retrieval should be a fallback/expansion mechanism, not the first source for structured project facts.

---

# 22. Candidate Scoring

For memory `m` and request `q`:

```text
score(m,q) =
    wr * semantic_relevance
  + wa * authority
  + wf * freshness
  + ws * scope_match
  + wd * dependency_match
  + wu * historical_utility
  + wc * confidence
  - wx * contradiction_risk
  - wt * token_cost
```

Hard filters before scoring:

```text
status must be active OR explicitly requested history
valid_from_event <= q.state_version
valid_to_event is NULL OR valid_to_event >= q.state_version
project_id must match
source events must exist
```

---

# 23. Staleness Detection

A context packet becomes **potentially stale** if relevant authoritative events occur after dispatch.

At submission:

```text
dispatch_version = context.state_version
current_version  = current event id
```

Compute:

```text
delta_events = events(dispatch_version + 1 ... current_version)
```

Relevant if they touch:
- same task;
- dependency tasks;
- declared/touched files;
- leased resources;
- selected memories;
- interfaces referenced by selected code context.

Then:

```text
staleness_score =
  relevant_delta_events
  + invalidated_memory_count
  + superseded_memory_count
  + dependency_change_count
```

Possible action:
- accept;
- revalidate;
- reject as stale;
- regenerate context and retry.

---

# 24. Context Compiler

The compiler turns retrieved state into the **smallest sufficient context packet**.

It is a compiler, not a chat-history dump.

## 24.1 Context classes

### C0 — Authoritative task core

Always included:
- task goal;
- acceptance criteria;
- explicit constraints;
- current state version;
- dependencies;
- budget;
- leases.

### C1 — Committed decisions

Only task-relevant active decisions.

### C2 — Code evidence

Files/symbols/snippets.

### C3 — Assumptions and open questions

Only unresolved relevant assumptions.

### C4 — Failures and recovery knowledge

Relevant prior failed attempts and known failure modes.

### C5 — Procedures

Validated project-specific instructions.

### C6 — Historical episode summaries

Lowest priority.

---

# 25. Static Context Budget v1

Before learned adaptation, use a deterministic allocator.

Example for a 24k-token budget:

```text
C0 authoritative core     reserve 3k
C1 decisions              max     2k
C2 code evidence          max    12k
C3 assumptions/questions  max     2k
C4 failures               max     2k
C5 procedures             max     2k
C6 episode history        max     1k
```

Unused budget flows downward to C2 first, then C4/C5.

---

# 26. Risk-Aware Context Allocation

Later:

Low-risk task:
- more compact context;
- fewer failure histories;
- fewer verification notes.

High-risk task:
- broader code evidence;
- dependency decisions;
- contradictory assumptions;
- relevant failure history;
- stronger provenance.

Example policy:

```python
if risk < 0.3:
    context_budget = base * 0.70
elif risk < 0.7:
    context_budget = base
else:
    context_budget = base * 1.25
```

The policy must still obey agent context limits and project budget.

---

# 27. Context Packet Schema

```json
{
  "context_id": "CTX_882",
  "project_id": "P1",
  "task_id": "T17",
  "agent_id": "codex_2",

  "state_version": 5821,
  "compiled_event": 5822,

  "goal": "...",
  "acceptance_criteria": [],

  "constraints": [],

  "dependency_state": [],

  "decisions": [
    {
      "memory_id": "M33",
      "text": "...",
      "source_events": [4221]
    }
  ],

  "assumptions": [
    {
      "memory_id": "M71",
      "text": "...",
      "confidence": 0.62,
      "status": "unverified"
    }
  ],

  "code_context": [
    {
      "path": "src/auth/client.py",
      "start_line": 50,
      "end_line": 130,
      "content_hash": "..."
    }
  ],

  "failures": [],
  "procedures": [],
  "open_questions": [],

  "leases": [],
  "risk_flags": [],

  "budget_remaining_tokens": 82000,
  "context_token_count": 22112,

  "memory_ids": ["M33", "M71"],

  "digest": "sha256:..."
}
```

---

# 28. Context Digest

Compute digest over canonical JSON.

Purpose:
- provenance;
- reproducibility;
- detect accidental mutation;
- compare contexts across experiments.

Submission must report:

```json
{
  "context_id": "CTX_882",
  "context_digest": "sha256:...",
  "dispatch_state_version": 5821
}
```

---

# 29. Agent Handoff

Handoff is not a transcript copy.

## Handoff procedure

```text
Agent A stops / task changes owner
          │
          ▼
append final agent events
          │
          ▼
update task state
          │
          ▼
extract/consolidate memory candidates
          │
          ▼
compile fresh context at CURRENT state_version
          │
          ▼
Agent B starts cold
```

Agent B does not receive Agent A's private reasoning trace.

It receives:
- authoritative task state;
- committed decisions;
- assumptions;
- evidence;
- relevant failures;
- code state;
- procedures.

---

# 30. Measuring Handoff Quality

Operational metrics:

### Handoff re-exploration tokens

Tokens spent by Agent B on tool calls retrieving information already present in Agent A's relevant context.

### First-valid-action latency

Events/time until Agent B produces its first action that contributes to accepted work.

### Handoff regression rate

Fraction of handoffs that cause:
- reversal of valid decision;
- stale edit;
- redundant patch;
- gate rejection attributable to missing context.

### Context preservation recall

Fraction of gold critical facts transferred.

---

# 31. Orchestrator Integration

The orchestrator owns:

```text
schedule_task()
reserve_budget()
grant_lease()
request_context()
dispatch_agent()
receive_patch()
run_gate()
trigger_recovery()
append_event()
```

Memory subsystem owns:

```text
process_event()
create_memory_candidates()
resolve_memory_updates()
retrieve()
compile_context()
record_context_feedback()
```

The memory subsystem cannot:
- merge code;
- grant leases;
- mutate task state directly;
- change budgets directly.

---

# 32. Python Interfaces

## 32.1 Event store

```python
class EventStore:
    def append(
        self,
        *,
        actor: str,
        kind: str,
        project_id: str,
        payload: dict,
        task_id: str | None = None,
        causation_id: int | None = None,
        correlation_id: str | None = None,
        fencing_token: int | None = None,
    ) -> int:
        ...

    def read_after(
        self,
        event_id: int,
        *,
        project_id: str
    ) -> list["Event"]:
        ...

    def current_version(self, project_id: str) -> int:
        ...
```

## 32.2 Memory lifecycle

```python
class MemoryLifecycle:
    def process_event(self, event: "Event") -> list[str]:
        # Return created/updated memory IDs.
        ...

    def consolidate(
        self,
        *,
        project_id: str,
        upto_event: int
    ) -> list[str]:
        ...

    def archive_low_value(
        self,
        *,
        project_id: str,
        upto_event: int
    ) -> list[str]:
        ...
```

## 32.3 Retriever

```python
class MemoryRetriever:
    def retrieve(
        self,
        request: "ContextRequest"
    ) -> "RetrievalResult":
        ...
```

## 32.4 Compiler

```python
class ContextCompiler:
    def compile(
        self,
        request: "ContextRequest",
        retrieval: "RetrievalResult",
        project_state: "ProjectState"
    ) -> "ContextPacket":
        ...
```

## 32.5 Feedback

```python
class ContextFeedbackRecorder:
    def record_submission(
        self,
        *,
        context_id: str,
        task_id: str,
        gate_result: str,
        memories_used: list[str],
        stale_memories: list[str],
        agent_feedback: dict,
    ) -> None:
        ...
```

---

# 33. Pydantic Models

Use Pydantic v2.

Required models:

```text
Event
ProjectState
TaskState
Lease
Memory
MemorySource
MemoryRelation
ContextRequest
RetrievalCandidate
RetrievalResult
ContextPacket
PatchSubmission
GateResult
RecoveryAction
```

All externally persisted payloads must validate before append.

---

# 34. Context Compilation Algorithm — v1

```text
INPUT:
    context request q
    project state s
    active memory M

1. Validate q.state_version == requested snapshot.
2. Fetch C0 authoritative core.
3. Fetch active committed decisions linked to:
       task
       dependencies
       touched/declared resources.
4. Resolve exact symbol/file evidence.
5. Retrieve failure/procedure candidates.
6. Run lexical retrieval.
7. Run vector expansion only if remaining evidence budget exists.
8. Remove:
       superseded memories
       expired memories
       duplicate memories
       memories outside validity interval.
9. Detect unresolved contradictions.
10. Allocate tokens by context class.
11. Rank within each class.
12. Pack until budget.
13. Canonicalize packet.
14. Hash packet.
15. Append context.compiled event.
16. Return immutable packet.
```

---

# 35. Adaptive Policy — v2

Do not implement until v1 generates useful logs.

Input features:

```text
task type
DAG depth
DAG fanout
number of dependencies
task attempt
declared file count
architectural-change flag
state-version lag distribution
recent gate rejection count
unresolved assumption count
memory contradiction count
retrieval candidate entropy
prior context utilization
budget burn
agent identity/model
```

Actions:

```text
context budget multiplier
retrieval strategy set
per-class token allocation
vector expansion depth
history depth
verification hint
```

Start with:
- logistic regression for risk;
- contextual bandit only if enough replayable episodes exist.

---

# 36. Context Utility Feedback

The system must learn what context was useful.

Direct utility signals:

### Strong positive
- memory cited by agent in final structured summary;
- source file changed based on selected code context;
- procedure used successfully;
- relevant decision preserved through gate.

### Strong negative
- memory identified stale;
- memory contradicted by accepted state;
- context contributed to rejected patch.

### Weak signals
- agent opened source referenced by memory;
- lexical overlap with patch explanation.

Do not train on hidden-test content.

---

# 37. "Used Context" Definition

A memory is considered **used** if at least one is true:

1. agent explicitly references its memory ID in structured final output;
2. associated source artifact/file participates in the accepted patch;
3. agent tool trajectory accesses the memory's linked symbol/path after dispatch;
4. a validated procedure memory's command is executed;
5. a decision memory is included in the agent's final decision record.

This is imperfect but operational.

---

# 38. Integration Gate

The combined project retains the reviewed serialized gate.

## G0
Rebase onto current integration branch.

## G1
Build / syntax / typecheck.

## G2
Visible tests on merged tree.

## G3
Risk-selected verification.

Core verification levels:

```text
V0 = G1 + G2
V1 = V0 + static analysis + coverage delta
V2 = V1 + independent reviewer
V3 = V2 + validated adversarial tests
```

Memory/context-related gate metadata:

```text
dispatch state version
gate state version
context age
staleness score
invalidated memory count
superseded memory count
context token count
retrieval strategies used
```

---

# 39. Recovery

Add context-specific failures to the existing recovery table.

| Failure | Detector | First action | Escalation |
|---|---|---|---|
| stale context | version delta | recompile context | reassign |
| superseded memory used | provenance check | invalidate + retry | reviewer |
| missing critical dependency context | gate/reviewer | dependency-aware recompile | replan |
| contradictory memory | conflict resolver | mark disputed + include both | human |
| context overflow | compiler | compress lower-priority class | switch larger-context model |
| repeated re-exploration | trajectory monitor | enrich exact context | handoff policy change |
| misleading summary | verifier/provenance | replace with source evidence | disable summarizer class |
| vector false positive overload | utilization metric | lower vector quota | lexical/structured-only |

All recovery actions are budgeted.

---

# 40. Side-Effect Recovery

Git rollback alone is not sufficient.

Agent environment:
- isolated container;
- isolated worktree;
- no network by default;
- pinned package mirror if required.

Checkpoint contains:
- git ref;
- container/environment snapshot identifier;
- state version;
- context ID;
- task ID.

---

# 41. Deterministic Replay

Replay is mandatory.

Replaying authoritative history must reconstruct:
- project state;
- task DAG;
- lease state;
- budgets;
- gate outcomes;
- all stored memory creation/update events;
- context metadata.

Important distinction:

> Replay should **not re-run LLM summaries** to reconstruct prior memory.

`memory.created` stores the generated content.

Therefore exact replay is possible.

If the current system wants to regenerate a better summary, it creates a **new memory version**, preserving the original.

---

# 42. Counterfactual Context Replay

Offline, for a recorded `context.requested` event:

```text
recorded project state
      +
recorded candidate memories
      +
alternative retrieval policy
      ↓
alternative context packet
```

This can evaluate:
- token count;
- gold-context recall;
- stale-memory selection;
- overlap with accepted patch evidence.

It cannot prove end-to-end task success without rerunning the agent.

Do not overclaim counterfactual end-to-end results.

---

# 43. CLI

Recommended commands:

```bash
arc init <repo>

arc run-task TASK_ID
arc status

arc events --after 500
arc replay RUN_ID

arc memory list
arc memory inspect MEMORY_ID
arc memory conflicts
arc memory rebuild-index
arc memory consolidate

arc context build TASK_ID --agent codex
arc context inspect CONTEXT_ID
arc context diff CONTEXT_A CONTEXT_B

arc gate PATCH_ID
arc recover TASK_ID

arc eval run CONFIG.yaml
arc eval analyze RUN_DIR
```

`arc` is a placeholder CLI name.

---

# 44. Configuration

Example:

```yaml
runtime:
  max_parallel_agents: 3
  single_writer: true

state:
  sqlite_path: .arc/state.db
  wal: true

memory:
  write_threshold: 2.5
  enable_vector: true
  enable_graph_relations: true
  enable_llm_candidate_extraction: false
  consolidation_interval_events: 100
  archive_after_events: 2000

context:
  default_budget_tokens: 24000
  min_authoritative_tokens: 3000
  max_decision_tokens: 2000
  max_code_tokens: 12000
  max_assumption_tokens: 2000
  max_failure_tokens: 2000
  max_procedure_tokens: 2000
  max_episode_tokens: 1000

staleness:
  reject_threshold: 0.8
  revalidate_threshold: 0.3

verification:
  default: V0
  high_risk: V2

budget:
  per_task_usd: 5.0
  per_project_usd: 500.0

isolation:
  network: false
  cpu_limit: 4
  memory_limit_gb: 8
```

All evaluation configs must be immutable and checked into the run artifact.

---

# 45. Repository Structure

```text
adaptive-agent-runtime/
├── README.md
├── pyproject.toml
├── configs/
│   ├── dev.yaml
│   ├── eval.yaml
│   └── policies/
│
├── runtime/
│   ├── orchestrator.py
│   ├── scheduler.py
│   ├── budgets.py
│   ├── leases.py
│   ├── gate.py
│   ├── recovery.py
│   └── replay.py
│
├── state/
│   ├── events.py
│   ├── projection.py
│   ├── models.py
│   ├── schema.sql
│   └── hashing.py
│
├── memory/
│   ├── models.py
│   ├── candidates.py
│   ├── lifecycle.py
│   ├── write_gate.py
│   ├── provenance.py
│   ├── conflicts.py
│   ├── consolidation.py
│   ├── forgetting.py
│   └── feedback.py
│
├── indexes/
│   ├── lexical.py
│   ├── vector.py
│   ├── symbols.py
│   └── relations.py
│
├── context/
│   ├── request.py
│   ├── retrieval.py
│   ├── ranking.py
│   ├── allocator.py
│   ├── compiler.py
│   ├── staleness.py
│   └── digest.py
│
├── isolation/
│   ├── container.py
│   ├── worktree.py
│   └── checkpoints.py
│
├── adapters/
│   ├── base.py
│   ├── codex.py
│   ├── claude.py
│   ├── opencode.py
│   └── openrouter.py
│
├── verification/
│   ├── static.py
│   ├── reviewer.py
│   └── adversarial_tests.py
│
├── eval/
│   ├── benchmark/
│   ├── context_pressure/
│   ├── faults/
│   ├── grading/
│   ├── baselines/
│   ├── runners/
│   └── analysis/
│
├── cli/
│   └── main.py
│
└── tests/
    ├── unit/
    ├── integration/
    ├── replay/
    └── end_to_end/
```

---

# 46. Implementation Order

Do not implement the folders alphabetically.

Use this exact dependency order.

## Phase 1 — deterministic substrate

1. event store;
2. projections;
3. task DAG;
4. isolated worktree runner;
5. integration gate;
6. budget accountant;
7. replay.

No vector DB yet.

## Phase 2 — static context system

8. context request;
9. authoritative context builder;
10. exact code/symbol lookup;
11. structured handoff packet;
12. context digest;
13. context feedback logging.

This gives the strongest static baseline.

## Phase 3 — versioned memory

14. memory schema;
15. deterministic memory candidates;
16. provenance;
17. validity intervals;
18. supersession;
19. conflict handling;
20. FTS retrieval.

## Phase 4 — adaptive retrieval

21. vector index;
22. candidate scorer;
23. budget allocator;
24. risk-aware context compiler;
25. lifecycle consolidation/archive.

## Phase 5 — learned policies

26. offline risk model;
27. offline write gate;
28. adaptive allocation policy;
29. replay screening.

Only reach this phase if earlier experiments justify it.

---

# 47. Unit Test Requirements

Minimum unit tests:

## Event store
- monotonic IDs;
- hash stable;
- replay identical;
- invalid payload rejected.

## Memory
- memory without source event rejected;
- superseded memory excluded by default;
- validity window enforced;
- conflict marks status;
- deleted derived memory does not alter event replay.

## Context
- deterministic packet for same inputs;
- digest stable;
- budget never exceeded;
- authoritative core never omitted;
- superseded memory never packed;
- invalid state version rejected.

## Leases
- old fencing token rejected.

## Budget
- hard task ceiling enforced.

---

# 48. Integration Tests

Required scenarios:

### IT1 — Cold handoff

Agent A completes half a task.
Agent B starts with no transcript.
Compiler reconstructs context.
Agent B continues.

### IT2 — Superseded API

Old API fact stored.
API changes.
Old memory must not be delivered.

### IT3 — Concurrent dependency change

Agent A dispatched at version N.
Agent B merges relevant interface change at N+20.
Agent A submission must be marked stale/revalidated.

### IT4 — Failed attempt memory

Attempt 1 fails for a known reason.
Attempt 2 must receive useful failure context.

### IT5 — Replay

Delete all projections and indexes.
Replay event log.
Final project projection and memory metadata hashes must match.

### IT6 — Archive

Archive old episode memories.
Critical decision/procedure remains retrievable.

---

# 49. Fault Injection

Extend the runtime fault injector with memory/context faults.

Injectable faults:

```text
STALE_STATE_READ
SUPERSEDED_MEMORY
MISSING_DECISION
WRONG_SUMMARY
VECTOR_DISTRACTOR
CONTRADICTORY_ASSUMPTION
CONTEXT_TRUNCATION
HANDOFF_WITHOUT_FAILURE_HISTORY
INDEX_CORRUPTION
AGENT_KILL
LEASE_EXPIRY
PATCH_CORRUPTION
BUDGET_EXHAUSTION
```

Measure detection and recovery separately.

---

# 50. Benchmark Strategy

A single benchmark is insufficient.

Use three layers.

## Layer A — Memory-isolation benchmarks

Purpose:
test memory mechanism without full multi-agent confounders.

Candidates:
- MemGym coding track;
- LongMINT GitHub-commit subset;
- ContextBench where appropriate.

Metrics:
- memory recall;
- update interference;
- retrieval precision;
- context token cost.

## Layer B — Repository coding benchmark

Construct 60–120 instances from real PRs.

Strata:

```text
S-small:
1–2 files
negative control

S-medium:
3–8 files
2+ modules

S-large:
10+ files
cross-module refactor / API migration / dependency update
```

## Layer C — Context-pressure variants

For each suitable task generate versions with:

```text
P0:
minimal prior history

P1:
useful prior decisions

P2:
long history + irrelevant events

P3:
superseded facts / changed APIs

P4:
multiple agent handoffs

P5:
failure history + recovery knowledge
```

This isolates the value of memory.

---

# 51. Benchmark Construction Requirements

Each repo instance must have:

- permissive license;
- buildable pre-state;
- container image;
- visible tests;
- hidden tests;
- golden patch;
- PR/issue specification;
- dependency lock;
- contamination metadata.

Hidden tests:
- absent from agent container;
- injected only at grading.

Prefer:
- post-model-cutoff PRs;
- lower-prominence repositories where possible.

---

# 52. Baselines

All baselines must be compute-matched.

## B0 — Single agent, full session

Strong baseline.

## B1 — Single-agent pipeline

```text
localize → patch → validate
```

## B2 — Static multi-agent transcript handoff

Manager + workers passing transcripts.

## B3 — Static structured handoff

Use project/task packet, no long-term memory.

This is the **most important memory baseline**.

## B4 — Rolling summary

One compressed project summary.

## B5 — Vector top-k memory

Standard embedding retrieval.

## B6 — Event-sourced static memory

Versioned memory but fixed retrieval rules.

## B7 — Full proposed runtime

Versioned adaptive memory + context compiler.

---

# 53. Evaluation Matrix

Do not evaluate every combination at first.

## Gate experiment

25–30 instances:

```text
B0
B1
B3
B5
B7-lite
```

where B7-lite is deterministic, not learned.

Goal:
determine whether context-management headroom exists.

## Final experiment

60–120 instances:
- selected strongest baselines;
- ≥3 seeds where budget allows;
- paired tasks;
- bootstrap confidence intervals.

---

# 54. Primary Metrics

## 54.1 Resolved rate @ iso-cost

A task is resolved iff:
- all hidden tests pass;
- no previously passing test regresses.

Primary headline metric.

## 54.2 Cost per resolved task

Include:
- model calls;
- embedding calls;
- context construction;
- verifier calls.

Do not hide memory-management cost.

---

# 55. Memory/Context Metrics

## Delivered context tokens

Actual tokens sent to the agent.

## Memory-management tokens

Tokens consumed creating, consolidating, or evaluating memory.

## Context precision

Among delivered retrievable units, fraction labeled relevant.

## Context recall

Fraction of gold relevant units delivered.

## Context utilization rate

Fraction of delivered memory/code units operationally used.

## Stale-memory delivery rate

```text
delivered stale memories / delivered memories
```

## Supersession miss rate

Fraction of retrievals where old memory is selected despite a valid superseding memory.

## Re-exploration ratio

Tokens/tool operations spent rediscovering information already present in recoverable project history.

## Handoff overhead

Cost from handoff until productive continuation.

---

# 56. Reliability Metrics

```text
gate rejection rate
regression rate
stale-context-caused rejection rate
injected-fault recovery rate
mean recovery cost
context invalidation rate
human interventions per task
```

---

# 57. Memory Efficiency Metrics

```text
active memory count
archived memory count
index size
retrieval p50 / p95 latency
consolidation cost
tokens stored vs tokens delivered
```

Report p95, not only averages.

---

# 58. Context Quality by Layer

Report context quality separately:

```text
authoritative state
code evidence
decisions
assumptions
failures
procedures
episodes
```

Otherwise a good code retriever may hide a bad memory system.

---

# 59. Ablations

Required:

### A1
No adaptive memory: static structured packet only.

### A2
No provenance/validity.

### A3
No supersession.

### A4
No forgetting/archive.

### A5
No vector retrieval.

### A6
Vector only.

### A7
No failure/procedure memory.

### A8
Full transcript at equal token budget.

### A9
No risk-aware allocation.

### A10
No state-version staleness check.

### A11
Packet vs transcript at identical delivered token count.

### A12
Same model vs heterogeneous agents.

---

# 60. Degenerate-Solution Guards

A claimed memory win is invalid if it comes from:
- sending more tokens;
- using a stronger model;
- more verifier calls;
- more wall-clock;
- lower parallelism;
- hidden test leakage.

Therefore every result table should include:

```text
resolved rate
USD cost
delivered tokens
management tokens
wall-clock
agent calls
verifier calls
```

---

# 61. Statistical Analysis

Use:
- paired per-task differences;
- bootstrap 95% confidence intervals;
- stratified results;
- effect sizes.

For success rate:
- paired bootstrap;
- McNemar test where appropriate.

For continuous costs:
- bootstrap median/mean difference.

Preregister:
- primary metric;
- exclusion criteria;
- task strata;
- equivalence margin for H1;
- stopping rule.

---

# 62. Acceptance Criteria

These are engineering/research goals, not guaranteed claims.

## AC1 — Correctness separation

Deleting memory indexes/projections must not alter authoritative replay.

**Pass condition:** 100%.

## AC2 — Replay

Full event replay reconstructs final authoritative state byte-identically or canonically equivalently.

**Target:** ≥95% full episode reproduction during development; 100% for final benchmark infrastructure.

## AC3 — Supersession

No memory known to be superseded may be delivered as active fact.

**Target:** ≥99% on deterministic update tests.

## AC4 — Context budget

No compiled packet exceeds declared budget.

**Pass condition:** 100%.

## AC5 — Hidden-test isolation

Agent container cannot access hidden tests.

**Pass condition:** 100%.

## AC6 — Stale-context detection

Injected stale-state faults detected.

**Target:** ≥90% for deterministic stale-version cases.

## AC7 — Handoff

Structured handoff reduces re-exploration relative to transcript-free cold start without lowering resolved rate.

## AC8 — End-to-end research target

On S-large and/or high-context-pressure strata, proposed method improves one of:

```text
resolved rate at equal cost
OR
cost at equivalent resolved rate
```

with confidence interval excluding zero for the selected primary comparison.

---

# 63. Go / No-Go Gates

## Gate 1 — End of Month 1

Can:
- event log replay;
- task runner;
- gate;
- static structured packet

operate end-to-end?

If no:
do not build adaptive memory.

## Gate 2 — End of Month 2

Does either:
- full transcript become inefficient;
- static context lose important information;
- stale/update interference measurably hurt agents

on the selected task strata?

If no:
adaptive memory has no demonstrated target.

Pivot to characterization.

## Gate 3 — End of Month 4

Does versioned memory beat:
- rolling summary;
- vector top-k;
- static structured handoff

on at least one reliability/cost tradeoff?

If no:
stop learned policy work.

Publish system/negative result if strong.

---

# 64. Six-Month Plan

## Month 1 — Authoritative substrate + replay

Deliver:
- SQLite event store;
- projections;
- worktree isolation;
- integration gate;
- budget accounting;
- deterministic replay;
- single-agent baseline;
- static structured context packet.

Paper outcome already possible:
- infrastructure methodology.

## Month 2 — Benchmark + context problem characterization

Deliver:
- 20–30 repo tasks;
- context-pressure variants;
- B0/B1/B3/B5;
- initial handoff metrics;
- stale-context injection.

Decision:
Does the problem materially exist?

## Month 3 — Versioned memory lifecycle

Deliver:
- memory schema;
- provenance;
- supersession;
- validity windows;
- FTS;
- failure/procedure memories;
- memory conflict classes T0–T2.

Experiments:
- H1;
- H2;
- handoff study.

## Month 4 — Adaptive context compiler

Deliver:
- vector expansion;
- candidate scorer;
- class budget allocator;
- risk-aware static policy;
- context feedback;
- context-specific recovery.

Experiments:
- H3 deterministic version;
- H4;
- H5.

A submittable result must exist by the end of this month.

## Month 5 — Offline learned policy + full evaluation

Deliver:
- risk model;
- optional learned write gate;
- counterfactual context replay;
- full 60–120 benchmark;
- ablations.

Only if data volume supports it:
- contextual bandit for allocation.

Do not make RL mandatory.

## Month 6 — Paper + OSS

Deliver:
- final paper;
- reproducible traces;
- benchmark manifests;
- container images;
- documentation;
- demo;
- CLI release.

---

# 65. First Two Weeks — Exact Engineering Tasks

## Day 1–2

Create repository and schemas:
- `Event`;
- `TaskState`;
- event SQLite table;
- canonical JSON hashing.

Tests:
- append;
- replay;
- hash stability.

## Day 3–4

Implement projections:
- project;
- task;
- budget.

Command:

```bash
arc replay
```

must reconstruct projections from empty DB projections.

## Day 5–6

Implement:
- git worktree creation;
- isolated task branch;
- basic Docker runner.

## Day 7

Implement gate:
- rebase;
- build command;
- visible tests;
- accepted/rejected events.

## Day 8–9

Implement static `ContextPacket`:
- spec;
- task state;
- dependencies;
- files;
- decisions placeholder.

No embeddings.

## Day 10

Implement context digest + dispatch event.

## Day 11–12

Implement one agent adapter.

Recommended first adapter:
- a CLI agent you can automate reliably.

Do not start with four adapters.

## Day 13

End-to-end:

```text
task
→ context
→ isolated agent
→ patch
→ gate
→ event log
→ replay
```

## Day 14

Freeze baseline v0.

Tag:

```text
baseline-static-context-v0
```

Every adaptive-memory improvement must compare against it.

---

# 66. Recommended Technology Stack

```text
Python               3.11+
Pydantic             v2
SQLite               WAL + FTS5
Docker               execution isolation
git worktree         patch isolation
tree-sitter          symbol extraction
ripgrep              lexical code lookup
hnswlib              optional vector index
pandas/polars        evaluation analysis
scipy/statsmodels    statistics
pytest               tests
Typer                 CLI
```

Optional:
- FastAPI dashboard backend;
- DuckDB for large trace analysis.

Avoid initially:
- Kubernetes;
- Neo4j;
- Kafka;
- distributed databases;
- custom RL infrastructure.

---

# 67. Model Adapter Contract

```python
class AgentAdapter(Protocol):
    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        ...
```

Return:

```json
{
  "status": "completed|failed|budget_exhausted",
  "patch_ref": "...",
  "summary": "...",
  "memory_references": [],
  "decisions": [],
  "assumptions": [],
  "tool_trace": [],
  "token_usage": {},
  "cost_usd": 0.0
}
```

---

# 68. Memory Producer Contract

Every LLM-produced memory must record:

```text
model ID
model version if available
prompt template version
prompt hash
input event IDs
output hash
temperature
```

This is necessary for reproducibility.

---

# 69. Security Boundaries

Memory should never automatically store:
- raw secrets;
- credentials;
- hidden tests;
- private external tokens.

Add a redaction pass before any model-generated memory candidate is persisted.

Agent containers:
- no host SSH;
- no host credential mounts;
- network disabled by default.

---

# 70. Failure Modes to Expect

## F1 — Summary drift

Repeated summaries distort original meaning.

Mitigation:
- summaries point to source events;
- important facts remain structured;
- do not summarize summaries recursively without provenance.

## F2 — Memory echo chamber

A wrong memory is retrieved repeatedly and reinforced.

Mitigation:
- memories never validate themselves;
- source-event authority;
- verifier feedback;
- contradiction checks.

## F3 — Over-consolidation

Distinct situations merged into one generic procedure.

Mitigation:
- preserve scope keys;
- conservative consolidation;
- reversible archive.

## F4 — Memory explosion

Every event becomes memory.

Mitigation:
- deterministic trigger list;
- write gate;
- consolidation;
- archival.

## F5 — Adaptive policy overfits benchmark

Mitigation:
- frozen Month-2 test split;
- held-out repositories;
- simple models;
- report calibration.

## F6 — Memory helps only because of more tokens

Mitigation:
- equal delivered-token ablation.

## F7 — Context compiler drops tacit information

Mitigation:
- transcript-vs-packet equal-budget ablation;
- handoff tests;
- critical-fact recall.

## F8 — Retrieval latency erases model savings

Mitigation:
- include management latency/cost;
- p95 reporting;
- exact/lexical before vector.

---

# 71. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---:|---:|---|
| Static handoff already sufficient | High | High | Month-2 gate |
| Adaptive memory adds no final-task value | Medium | High | publish characterization |
| Benchmark construction overruns | High | High | 30-task gate first |
| Context relevance ground truth expensive | High | Medium | use existing context benchmarks + sampled manual labels |
| Learned policy lacks data | High | Medium | deterministic policy is complete method |
| API costs explode | Medium | High | hard budget + replay |
| Vector retrieval dominates engineering time | Low | Medium | optional derived index |
| Replay not deterministic | Medium | High | fix before adaptive layer |
| Agent tool formats unstable | Medium | Medium | adapter boundary |
| Memory corruption | Medium | High | event provenance + rebuild |
| Generated summary leakage | Low | High | secret redaction |
| Model contamination | Medium | High | post-cutoff / low-prominence PRs |

---

# 72. Budget Strategy

Do not run the full factorial experiment.

Recommended:

## Month 2

```text
5 configs
25 tasks
2 seeds
250 runs
```

Cheap models first.

## Months 3–4

Focus only on:
- static handoff;
- vector memory;
- versioned memory;
- proposed deterministic compiler.

## Month 5

Select:
- strongest single-agent baseline;
- strongest static multi-agent baseline;
- strongest non-adaptive memory baseline;
- proposed method;
- 3–5 key ablations.

Use:
- 60–100 instances;
- 2–3 seeds depending budget.

Every run has:
- hard USD ceiling;
- hard wall-clock ceiling;
- hard token ceiling.

---

# 73. Paper Framing

Do **not** title the paper:

> Adaptive Memory for Multi-Agent Coding

Too broad and too close to existing work.

Better:

> **Reliable Context Control for Long-Horizon Multi-Agent Coding**

Subtitle:

> **Event-Sourced State, Versioned Memory, and Risk-Aware Context Compilation**

---

# 74. Paper Contribution Statement

Potential contribution list:

1. **A correctness-preserving memory architecture** that separates authoritative project state from lossy adaptive memory.

2. **Versioned memory semantics** with event provenance, validity intervals, supersession, and stale-context detection for evolving software projects.

3. **A task/risk/budget-aware context compiler** that constructs per-agent handoff context from structured state, repository evidence, and adaptive memory.

4. **A replayable multi-agent runtime** integrating isolated worktrees, a serialized integration gate, budget accounting, and context-aware recovery.

5. **An evaluation protocol** combining repository-scale hidden-test tasks, context-pressure variants, handoff measurements, stale-memory fault injection, and iso-cost comparison.

6. **A characterization of the crossover point** where adaptive context management begins or fails to pay off.

A negative result remains valuable if executed rigorously.

---

# 75. Strongest Possible Scientific Claim

The strongest credible claim is not:

> Memory makes agents smarter.

It is:

> **For long-horizon repository tasks with evolving project state, treating agent memory as a versioned, non-authoritative projection and compiling task-specific context from that state can reduce stale-context and handoff failures while improving the reliability/cost tradeoff relative to static transcript, summary, and vector-memory baselines.**

That claim is:
- specific;
- measurable;
- falsifiable;
- differentiated from nearby work.

---

# 76. Open-Source Positioning

One-line product pitch:

> **A shared context control plane for coding agents: remember the right project state, hand it to the right agent, and never confuse a lossy summary with ground truth.**

Possible user experience:

```bash
arc init .

arc agent add codex
arc agent add claude
arc agent add opencode

arc run issue-142

# later
arc status
arc context inspect CTX_123
arc memory why M_77
arc replay RUN_9
```

The killer debugging feature should be:

```bash
arc memory why M_77
```

Output:

```text
Memory M_77

Type:
  decision

Current status:
  active

Derived from:
  event 4812 — gate.accepted
  event 4799 — decision.recorded

Valid:
  event 4812 → current

Delivered to:
  T17 / codex_2
  T21 / claude_1

Downstream outcomes:
  2 accepted patches
  0 rejected patches
```

This makes memory inspectable rather than magical.

---

# 77. What NOT to Build

For the first publishable version, explicitly reject:

```text
❌ generic agent marketplace
❌ arbitrary graph DB
❌ full RL controller
❌ autonomous model fine-tuning
❌ web dashboard before CLI
❌ distributed multi-machine scheduler
❌ multi-user cloud backend
❌ semantic conflict "solver"
❌ 10 different model providers
❌ personal memory
```

These add engineering volume but not scientific clarity.

---

# 78. Definition of MVP

The MVP is complete when all of this works:

```text
1 repository
2 heterogeneous agents
event-sourced state
isolated worktrees
single integration gate
static task DAG
versioned memory
provenance
supersession
FTS retrieval
optional vector expansion
context compiler
structured handoff
state-version staleness detection
budget accounting
replay
hidden-test grader
fault injector
evaluation runner
```

No learned policy is required for MVP.

---

# 79. Definition of Research-Complete

Research-complete requires:

- preregistered hypotheses;
- benchmark;
- strong baselines;
- iso-cost evaluation;
- context-pressure strata;
- ≥3 key ablations;
- handoff experiment;
- stale-memory experiment;
- replay release;
- statistical confidence intervals;
- cost accounting;
- failure analysis.

---

# 80. Final Recommended Priority

If time becomes constrained, implement in this order:

```text
P0  event sourcing + replay
P0  static structured context
P0  hidden-test benchmark
P0  provenance + supersession
P0  stale-context detection

P1  failure/procedure memory
P1  FTS retrieval
P1  context compiler
P1  handoff experiment

P2  vector retrieval
P2  consolidation/archive
P2  risk-aware allocation

P3  learned write gate
P3  contextual bandit
P3  graph retrieval
```

If the project reaches only P0 + P1 but evaluates them rigorously, it can still make a defensible thesis.

---

# 81. Final Decision

The two directions should be merged, but with a strict architectural boundary:

```text
Reliable Multi-Agent Coding Runtime
            │
            │ provides correctness substrate
            ▼
Authoritative Event-Sourced Project State
            │
            │ produces versioned derived knowledge
            ▼
Adaptive Memory Lifecycle
            │
            │ retrieves + budgets + compiles
            ▼
Per-Agent Context
            │
            ▼
Isolated Agent Execution
            │
            ▼
Serialized Integration Gate
            │
            └──────────────► new authoritative events
```

This closes the most important open question in the reviewed runtime:

> How should context be constructed during long-running, heterogeneous, multi-agent software work without either replaying the full transcript or losing the information that made previous work successful?

The answer proposed here is:

> **Never hand agents history. Hand them a versioned, provenance-aware compilation of the current project state and the minimum useful derived memory for their task.**

That is the implementation target.

---

# References / Required Reading

The exact bibliography should be frozen before paper submission. At minimum, review and cite:

1. **ContextBench: A Benchmark for Context Retrieval in Coding Agents** — arXiv:2602.05892.
2. **Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers** — arXiv:2603.07670.
3. **LongMINT: Evaluating Memory under Multi-Target Interference in Long-Horizon Agent Systems** — arXiv:2605.18565.
4. **MemGym: a Long-Horizon Memory Environment for LLM Agents** — arXiv:2605.20833.
5. **Choosing How to Remember: Adaptive Memory Structures for LLM Agents / FluxMem** — arXiv:2602.14038.
6. **Learning What to Retain: Gated-Memory Routing for Efficient Collaboration in Multi-Agent LLM Systems** — arXiv:2609.00237.
7. **ESAA-Conversational: An Event-Sourced Memory Layer for Continuity, Handoff, and Curation Across Heterogeneous LLM Coding Agents** — arXiv:2606.23752.
8. Strong single-agent coding baselines and pipeline approaches such as SWE-agent / OpenHands / Agentless-style systems.
9. Distributed-systems foundations: event sourcing, optimistic concurrency, leases, fencing tokens.
10. Software-engineering foundations: CI gating, merge queues, worktree/branch isolation.

---

# Appendix A — Minimal Context Request Example

```json
{
  "context_request_id": "CR_1",
  "project_id": "demo",
  "task_id": "T4",
  "agent_id": "codex",
  "state_version": 1004,
  "goal": "Migrate AuthClient login response to AuthResult.",
  "task_type": "api_migration",
  "risk": 0.78,
  "files_declared": [
    "src/auth/**",
    "src/api/**"
  ],
  "symbols": [
    "AuthClient.login",
    "AuthResult"
  ],
  "dependencies": [
    "T2"
  ],
  "token_budget": 24000,
  "agent_context_limit": 128000
}
```

---

# Appendix B — Minimal Memory Example

```json
{
  "memory_id": "M44",
  "project_id": "demo",
  "type": "decision",
  "representation": "DECISION_RECORD",
  "content": {
    "decision": "All auth APIs return domain result objects, not tuples.",
    "rationale": "Standardize error handling."
  },
  "created_event": 850,
  "valid_from_event": 850,
  "valid_to_event": null,
  "state_version_at_write": 850,
  "status": "active",
  "superseded_by": null,
  "confidence": 1.0,
  "importance": 0.95,
  "predicted_reuse": 0.90,
  "source_events": [
    842,
    850
  ]
}
```

---

# Appendix C — Minimal Context Packet Example

```json
{
  "context_id": "CTX_52",
  "project_id": "demo",
  "task_id": "T4",
  "agent_id": "codex",
  "state_version": 1004,
  "goal": "Migrate AuthClient login response to AuthResult.",
  "acceptance_criteria": [
    "Visible auth tests pass",
    "No tuple return remains in public auth API"
  ],
  "constraints": [
    "Do not modify hidden tests",
    "No network access"
  ],
  "decisions": [
    {
      "memory_id": "M44",
      "text": "All auth APIs return domain result objects, not tuples.",
      "source_events": [842, 850]
    }
  ],
  "assumptions": [],
  "failures": [],
  "procedures": [
    {
      "memory_id": "M18",
      "text": "Run auth integration tests with postgres service enabled."
    }
  ],
  "code_context": [
    {
      "path": "src/auth/client.py",
      "start_line": 20,
      "end_line": 150,
      "content_hash": "..."
    }
  ],
  "leases": [
    {
      "resource": "src/auth/**",
      "fencing_token": 91
    }
  ],
  "budget_remaining_tokens": 76000,
  "context_token_count": 19640,
  "memory_ids": ["M44", "M18"],
  "digest": "sha256:..."
}
```

---

# Appendix D — Core Evaluation Table Template

| System | Stratum | Resolved % | $ / task | $ / resolved | Delivered tokens | Memory mgmt tokens | Stale delivery % | Re-exploration % | p95 retrieval ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Single agent | S-small | | | | | | | | |
| Static packet | S-small | | | | | | | | |
| Vector memory | S-small | | | | | | | | |
| Proposed | S-small | | | | | | | | |
| Single agent | S-large | | | | | | | | |
| Static packet | S-large | | | | | | | | |
| Vector memory | S-large | | | | | | | | |
| Proposed | S-large | | | | | | | | |

---

# Appendix E — Core Principle

When implementation choices become ambiguous, use this test:

> **If this memory object disappeared, could authoritative replay still tell us what actually happened?**

If the answer is **no**, that information belongs in the authoritative event/state plane, not adaptive memory.

If the answer is **yes**, it may safely live in the adaptive memory plane.

This rule should prevent most architectural mistakes in the project.
