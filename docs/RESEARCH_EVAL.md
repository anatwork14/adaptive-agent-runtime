# ARC Research Evaluation

ARC 0.11 introduced the trace-derived evaluation contract. ARC 0.12 keeps that contract and normalizes **B3, B5, and B7** behind one execution/gating path.

The purpose is not to make ARC look better. The purpose is to make context/memory claims **falsifiable, reproducible, and auditable**.

For the exact B3/B5/B7 treatment definitions, see `docs/BASELINE_NORMALIZATION.md`.

## Core rules

> **Unknown telemetry stays unknown. ARC does not fabricate research measurements.**

> **Only the context policy may change across a normalized B3/B5/B7 treatment.**

The earlier prototype evaluation code contained placeholder values such as fixed cost, fixed token counts, and a retrieval-latency field that actually measured the entire task. Those values are not suitable for a paper and are removed from the research measurement path.

ARC distinguishes:

```text
observed fact                       research representation
─────────────────────────────────────────────────────────────
context.compiled token_count      → context_tokens
context.compiled policy           → context_policy
context.compiled stale IDs        → stale_memory_ids
context.policy_measured retrieval → retrieval_latency_ms
context.policy_measured compile   → context_compile_latency_ms
budget.consumed tokens > 0        → provider_tokens
budget.consumed USD > 0           → cost_usd
gate outcome                      → resolved / rejection stage
wall-clock task execution         → end_to_end_latency_ms
unavailable provider billing      → null
```

A `0` emitted by older provider adapters is conservatively treated as unavailable for research reporting unless there is positive evidence of usage. This avoids turning “provider did not report billing” into “the task cost $0.”

## Correctness boundary

Evaluation never bypasses ARC's runtime correctness model:

```text
manifest
   ↓
ContextPolicy (B3 / B5 / B7)
   ↓
immutable ContextPacket
   ↓
same AgentAdapter + AgentBudget
   ↓
isolated worktree
   ↓
exact Git candidate
   ↓
staleness detector
   ↓
IntegrationGate
   ↓
hidden grading (optional)
   ↓
trace-derived research measurement
```

A baseline is not allowed to define its own easier acceptance rule.

## Benchmark manifest

A benchmark manifest fixes the experimental contract before execution.

Example:

```yaml
benchmark_id: normalized-context-sequence
baseline: B7
execution_mode: sequence
seed: 7
agent_profile: builder
model: provider-model-name
repo_commit: 0123456789abcdef
context_token_budget: 8000
hard_task_usd: 1.0
faults: []
tasks:
  - task_id: T001
    goal: Fix the parser without changing the public API.
    files: [src/parser.py, tests/test_parser.py]
    acceptance: [Existing tests pass, New edge case passes]
    risk: 0.4
    token_budget: 8000
```

Every task must use the manifest's `context_token_budget`. This is an intentional fail-closed rule for matched-ceiling experiments.

The package includes matched templates:

```text
eval/examples/normalized_b3.yaml
eval/examples/normalized_b5.yaml
eval/examples/normalized_b7.yaml
```

Replace the placeholder repository SHA, model, agent, and task surface before a real run.

## Ordered long-horizon sequence semantics

ARC currently supports `execution_mode: sequence`.

The task list is ordered and represents one trajectory:

```text
S0 --T1--> S1 --T2--> S2 --T3--> ...
```

Accepted earlier work changes Git/event/memory state available to later tasks. Therefore:

- task order is part of the benchmark contract;
- reordering the same task IDs makes manifests incomparable;
- different baseline outcomes may cause trajectories to diverge later in the sequence;
- every B3/B5/B7 run must begin from an **independent reset of the same declared initial Git and ARC state**.

ARC 0.12 does not yet automate independent-reset benchmark farms; the researcher/operator must establish those isolated starting states.

## Normalized baselines in ARC 0.12

| ID | Policy | Execution status |
|---|---|---|
| B0 | single uninterrupted agent | not normalized yet |
| B2 | raw transcript handoff | not normalized yet |
| B3 | static structured, no long-term memory | normalized |
| B5 | deterministic naive vector top-k (`k=5`) | normalized |
| B7 | provenance/version-aware ARC runtime | normalized |

`ExperimentRunner` accepts B3/B5/B7 and routes all three through the same `Orchestrator.execute_task` path.

B5 uses ARC's deterministic lexical-hash vector representation. It must not be described as a semantic-embedding baseline unless a real pinned semantic embedding model is introduced and recorded separately.

## Matched ceiling vs exact iso-token

The manifest fixes the same **hard context-token ceiling** for each treatment.

That does not imply identical delivered token counts. A policy may use less of the ceiling because it found less relevant context or, in B3's case, intentionally retrieves no memory.

Therefore report both:

```text
resolved rate @ matched hard ceiling
actual delivered context tokens
```

Do not call the current design exact “iso-token” unless delivered-token distributions are separately matched.

## Comparable-manifest gate

Before two baseline result sets are compared, `validate_comparable_manifests(a, b)` requires equality of:

- execution mode;
- initial repository commit;
- context-token ceiling;
- per-task USD ceiling;
- agent profile;
- model identifier;
- seed metadata;
- fault declarations;
- ordered task IDs;
- task goals;
- declared files;
- acceptance criteria;
- risk;
- task token budgets;
- hidden-test pattern.

Only the baseline treatment may differ.

This prevents an apparent improvement from actually being caused by a larger context window, different model, easier tests, different source tree, reordered sequence, or different fault schedule.

## Task measurements

Each task produces a serializable `TaskMeasurement` containing, where observed:

```text
benchmark / baseline / task / agent / model / seed
initial repo commit
resolved + gate status + rejection stage
context ID + digest + actual policy
hard context budget + delivered context tokens
memory IDs + stale-memory IDs
retrieval strategy IDs
provider tokens + measurement availability
USD cost + measurement availability
end-to-end latency
retrieval latency
context compile latency
staleness score
stale memories delivered
retry / handoff / gate-failure counts
hidden-test outcome
fault declarations
event interval
candidate commit SHA
```

The event interval lets a later auditor return to the authoritative log that generated the research row.

## Result files

Per-task rows use canonical JSONL:

```python
from eval import write_measurements_jsonl

write_measurements_jsonl("results/run.jsonl", runner.last_measurements)
```

Read them back with schema validation:

```python
from eval import read_measurements_jsonl

rows = read_measurements_jsonl("results/run.jsonl")
```

Summaries use JSON and include telemetry coverage. A mean cost without coverage is not sufficient evidence.

## Coverage

For provider cost and token usage, ARC reports both value and coverage:

```text
mean_cost_usd = 0.18
cost_coverage = 0.72
```

means only 72% of tasks had observable billing telemetry. It must not be reported as if all tasks were measured.

If coverage is zero:

```text
mean_cost_usd = null
cost_coverage = 0.0
```

## Latency

ARC now separates:

- `end_to_end_latency_ms`: full orchestrator call;
- `retrieval_latency_ms`: directly measured policy retrieval phase;
- `context_compile_latency_ms`: directly measured packet compilation phase.

The harness never copies end-to-end latency into another field merely to populate a table.

## Hidden tests

`HiddenTestGrader` grades the integrated result after the normal gate. Hidden tests remain outside the agent-visible task context.

A task counts as resolved only when:

```text
IntegrationGate == ACCEPTED
AND
hidden_tests_passed is not False
```

If no hidden grader is configured, hidden-test fields remain null rather than being marked passed.

## Faults

The existing `FaultInjector` supports scenarios including stale state, superseded memory, missing decisions, wrong summaries, distractors, truncation, missing failure history, index corruption, agent kill, lease expiry, patch corruption, and budget exhaustion.

Fault-enabled manifests still fail closed in ARC 0.12 because a deterministic shared intervention schedule has not yet been wired into the normalized runner. Undeclared or differently scheduled intervention would invalidate a paired comparison.

## Primary experiment enabled by 0.12

The first serious study can now compare:

```text
B3 static structured
        vs
B5 naive vector top-k (k=5)
        vs
B7 provenance/version-aware ARC
```

from independent resets of the same initial state and the same ordered sequence.

Primary outcomes:

```text
resolved rate @ matched hard ceiling
actual context tokens / resolved task
stale-memory delivery rate
hidden-test pass rate
retry / gate-rejection rate
provider tokens / resolved task (when observable)
USD / resolved task (when observable)
retrieval p95
end-to-end p95
```

## What ARC 0.12 does not claim yet

ARC 0.12 does **not** claim:

- B7 is better than B3/B5;
- a repository-scale benchmark has already been run;
- exact delivered-token equality across policies;
- provider sampling seeds are enforced by every adapter;
- all providers expose trustworthy billing/token telemetry;
- B5 is a semantic-embedding baseline;
- B0/B2 are normalized fair competitors;
- fault schedules are normalized;
- independent-reset benchmark environments are automatically provisioned.

Those are experimental or future-harness tasks, not values to fill in by assumption.

The goal of ARC 0.12 is to make the **context policy** the primary controlled difference between B3, B5, and B7 while preserving the same execution and correctness boundary.
