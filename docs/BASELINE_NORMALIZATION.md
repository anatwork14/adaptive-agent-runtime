# ARC 0.12 — Normalized Context Baselines

ARC 0.12 turns B3, B5, and B7 into executable treatments behind one shared runtime path.

The purpose is to isolate the **context policy** as the experimental variable. A baseline is no longer allowed to execute its own agent, invent its own budget, or bypass ARC's normal transactional acceptance boundary.

## Shared execution path

All normalized treatments run through:

```text
fixed manifest + ordered task sequence
              │
              ▼
       ContextPolicy.build()
              │
      ┌───────┼────────┐
      │       │        │
     B3      B5       B7
      │       │        │
      └───────┼────────┘
              ▼
      immutable ContextPacket
              ▼
        same AgentAdapter
              ▼
        same AgentBudget
              ▼
      same isolated worktree
              ▼
      same candidate commit
              ▼
      same staleness detector
              ▼
       same IntegrationGate
              ▼
      same hidden grading
              ▼
     same trace measurement
```

`Orchestrator.execute_task(..., context_policy=...)` is the normalization seam. Omitting the argument keeps production behavior and selects B7.

## Treatment definitions

### B3 — static structured context

B3 receives:

- authoritative task goal;
- acceptance criteria;
- project constraints;
- dependency identifiers;
- declared code evidence;
- lease metadata;
- the same declared hard context ceiling.

B3 deliberately receives **no long-term memory retrieval**.

Retrieval strategy recorded in the trace:

```text
static_no_memory
```

### B5 — naive vector top-k

B5 uses the same persisted memory corpus but intentionally ignores temporal validity and supersession when selecting candidates.

The v0.12 policy is fixed to:

```text
naive_vector_topk:k=5
```

The vector substrate is ARC's deterministic signed lexical-hash embedding. This is useful because it is reproducible across processes and machines, but it is **not a semantic embedding model**. Results from B5 in ARC 0.12 must therefore be described as a deterministic vector/top-k baseline, not as a state-of-the-art semantic retriever.

Deleted memories are excluded from B5's corpus. Superseded, archived, disputed, or temporally stale memories remain eligible, which is intentional: B5 represents a retrieval system without ARC's version/provenance validity filter.

### B7 — ARC provenance-aware runtime

B7 is the normal production context path:

- active authoritative facts/decisions/constraints;
- dependency-linked memory;
- failures and procedures;
- lexical retrieval;
- vector expansion;
- provenance-aware ranking;
- temporal validity filtering;
- supersession filtering.

B7 remains the default when no research policy is injected.

## What is matched

For a valid B3/B5/B7 comparison, manifests must keep constant:

- initial repository commit;
- ordered task sequence;
- task goals;
- declared files;
- acceptance criteria;
- risk;
- hard context-token ceiling;
- hard per-task USD ceiling;
- agent profile;
- model identifier;
- seed metadata;
- hidden-test contract;
- fault declarations;
- execution mode.

All three treatments also share the same worktree, candidate, staleness, gate, recovery, and grading implementations.

## Hard ceiling is not delivered-token equality

`context_token_budget` is a **hard maximum**, not a promise that every policy will consume exactly the same number of context tokens.

For example, B3 may deliver fewer tokens because it intentionally has no memory to fill memory classes. B5/B7 may use more of the same ceiling when relevant memories exist.

Therefore a paper must report both:

```text
resolved rate @ same hard context ceiling
actual context tokens delivered per task
```

Do not call a result "iso-token" unless the actual delivered-token distributions are additionally controlled or matched. ARC 0.12 establishes **matched ceilings**, not exact delivered-token equality.

## Ordered long-horizon sequence semantics

ARC 0.12 retains v0.11's `execution_mode: sequence` design.

A run is a trajectory:

```text
S0 --T1--> S1 --T2--> S2 --T3--> ...
```

Accepted earlier tasks alter the Git/event/memory state available to later tasks. This is the intended long-horizon setting.

Consequently:

- task order is part of the treatment contract;
- reordering tasks makes manifests incomparable;
- B3/B5/B7 trajectories may diverge after different accepted/rejected outcomes;
- every baseline run must begin from an **independent reset** of the same declared initial repository and ARC state.

Do not run B3 and then B5 sequentially in the same already-mutated ARC project and call that a paired comparison.

## Observable policy telemetry

ARC emits a task-scoped `context.policy_measured` event after context construction:

```text
context_id
context_policy
retrieval_latency_ms
context_compile_latency_ms
retrieval_strategies
```

The corresponding `context.compiled` event records:

```text
hard_budget
actual token_count
memory_ids
stale_memory_ids
retrieval_strategies
memory_validity_enforced
```

`TaskMeasurement` preserves:

- actual context policy;
- retrieval strategy identifiers;
- delivered memory IDs;
- delivered stale-memory IDs;
- retrieval latency;
- context compilation latency;
- provider telemetry when actually observed;
- candidate commit SHA;
- gate outcome and hidden-test outcome.

## Stale-memory measurement

The compiler now records whether a selected memory is stale at the dispatch state.

B7 rejects stale/superseded memories before packing them.

B5 is allowed to pack them by design, so this outcome becomes directly measurable:

```text
stale_memories_delivered = len(stale_memory_ids)
```

This supports one of ARC's original hypotheses: provenance/version-aware context control should reduce stale-context delivery under long-horizon evolution.

## Stable ContextPacket digest

`compiled_event` is allocated only after the context payload is persisted. ARC therefore excludes that volatile event identifier from `compute_context_digest`.

The final immutable packet now satisfies:

```text
packet.digest == compute_context_digest(packet.model_dump())
```

This closes an auditability bug where the packet's event ID changed after the digest had already been computed.

## Example manifests

The package includes matched structural templates:

```text
eval/examples/normalized_b3.yaml
eval/examples/normalized_b5.yaml
eval/examples/normalized_b7.yaml
```

They are intentionally identical except for `baseline`. Replace the placeholder repository SHA, task surface, model, and agent with the actual benchmark contract before execution.

Before comparing any pair, call:

```python
validate_comparable_manifests(a, b)
```

## What remains outside v0.12

ARC 0.12 still does not normalize:

- B0 single uninterrupted control;
- B2 raw transcript handoff;
- deterministic fault scheduling;
- independent-reset task evaluation;
- a pinned semantic embedding provider;
- provider sampling-seed enforcement;
- automatic multi-repository benchmark reset/checkout.

Those limitations must remain explicit in any empirical claim.

## First valid experiment after 0.12

The first useful repository-scale study is now:

```text
B3 static structured
vs
B5 naive vector top-k (k=5)
vs
B7 provenance/version-aware ARC
```

under independent resets of the same initial state and the same ordered task sequence.

Primary outputs should include:

```text
resolved rate @ matched hard ceiling
actual context tokens / resolved task
stale-memory delivery rate
hidden-test pass rate
retry / gate-rejection rate
provider tokens / resolved task when observable
USD / resolved task when observable
retrieval p95
end-to-end p95
```

The point of 0.12 is not to claim that B7 wins. It is to make a B7 win or loss attributable to the context treatment rather than to a different executor or acceptance rule.
