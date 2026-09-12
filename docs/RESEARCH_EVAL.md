# ARC Research Evaluation

ARC 0.11 turns the existing `eval/` package into a stricter research measurement layer.

The purpose is not to make ARC look better. The purpose is to make context/memory claims **falsifiable, reproducible, and auditable**.

## Core rule

> **Unknown telemetry stays unknown. ARC does not fabricate research measurements.**

The previous prototype runner contained placeholder values such as fixed cost, fixed token counts, and a retrieval-latency field that actually measured the whole task. Those values are not suitable for a paper and are removed from the measurement path.

ARC 0.11 distinguishes:

```text
observed fact                  research representation
────────────────────────────────────────────────────────
context.compiled token_count → context_tokens
budget.consumed tokens > 0   → provider_tokens
budget.consumed USD > 0      → cost_usd
gate outcome                 → resolved / rejection stage
wall-clock task execution    → end_to_end_latency_ms
unmeasured retrieval phase   → null
unmeasured compile phase     → null
unavailable provider billing → null
```

A `0` emitted by older provider adapters is conservatively treated as unavailable for research reporting unless there is positive evidence of usage. This avoids turning “provider did not report billing” into “the task cost $0.”

## Correctness boundary

Evaluation never bypasses ARC's runtime correctness model:

```text
baseline context policy
        ↓
agent execution
        ↓
isolated worktree
        ↓
exact Git candidate
        ↓
IntegrationGate
        ↓
hidden grading (optional)
        ↓
research measurement
```

A baseline is not allowed to define its own easier acceptance rule.

## Benchmark manifest

A benchmark manifest fixes the experimental contract before execution.

Example:

```yaml
benchmark_id: arc-context-iso-budget
baseline: B7
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

Every task must use the manifest's `context_token_budget`. This is an intentional fail-closed rule for matched-budget experiments.

See `eval/examples/iso_budget_b7.yaml`.

## Baselines

The intended ARC context study uses:

| ID | Policy | Role |
|---|---|---|
| B0 | single uninterrupted agent | lower-bound/control |
| B2 | raw transcript handoff | handoff baseline |
| B3 | static structured context | strongest simple structured baseline |
| B5 | vector top-k memory | conventional retrieval baseline |
| B7 | versioned/provenance-aware ARC runtime | proposed system |

ARC 0.11 initially permits the trace-derived `ExperimentRunner` to execute **B7 only**. This is deliberate. Existing B0/B2/B3/B5 prototype classes do not yet share a fully equivalent context-budget/gate contract, so the runner refuses to generate a misleading cross-baseline result table from them.

The next evaluation step is to migrate those baseline policies behind one shared execution/gating interface.

## Comparable-manifest gate

Before two baseline result sets are compared, `validate_comparable_manifests(a, b)` requires equality of:

- repository commit;
- context token budget;
- per-task USD ceiling;
- agent profile;
- model;
- seed;
- fault declarations;
- task IDs;
- goals;
- declared files;
- acceptance criteria;
- risk;
- task token budgets;
- hidden-test pattern.

Only the baseline policy may differ.

This prevents an apparent improvement from actually being caused by a larger context window, different model, easier tests, different source tree, or different fault schedule.

## Task measurements

Each task produces a serializable `TaskMeasurement` containing, where observed:

```text
benchmark / baseline / task / agent / model / seed
repo commit
resolved + gate status + rejection stage
context ID + digest + hard budget + delivered context tokens
memory IDs
provider tokens + measurement availability
USD cost + measurement availability
end-to-end latency
retrieval latency (nullable)
context compile latency (nullable)
staleness score
stale memories delivered (nullable until historically measurable)
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

ARC separates latency concepts:

- `end_to_end_latency_ms`: actual task execution observed around the full orchestrator call;
- `retrieval_latency_ms`: null until retrieval is instrumented separately;
- `context_compile_latency_ms`: null until compiler latency is instrumented separately.

The harness never copies end-to-end latency into another field merely to populate a table.

## Hidden tests

`HiddenTestGrader` can grade the integrated result after the normal gate. Hidden tests stay outside the agent-visible task context.

A task counts as resolved only when:

```text
IntegrationGate == ACCEPTED
AND
hidden_tests_passed is not False
```

If no hidden grader is configured, the hidden-test fields remain null rather than being marked passed.

## Faults

The existing `FaultInjector` supports research scenarios including:

- stale state read;
- superseded memory;
- missing decision;
- wrong summary;
- vector distractor;
- contradictory assumption;
- context truncation;
- handoff without failure history;
- index corruption;
- agent kill;
- lease expiry;
- patch corruption;
- budget exhaustion.

Faults used by an experiment must be declared in the manifest and recorded in each affected measurement. Undeclared intervention invalidates a reproducible comparison.

## Primary experiment

The first serious paper-oriented study should compare:

```text
B3 static structured
        vs
B5 vector top-k
        vs
B7 versioned/provenance-aware ARC
```

under the same repository SHA, task set, model, seed, hidden tests, fault schedule, token budget, and USD ceiling.

B2 should then stress handoff depth, and B0 should provide a single-agent control.

Primary outcomes:

```text
resolved rate @ matched budget
context tokens per resolved task
provider tokens per resolved task (when observable)
USD per resolved task (when observable)
retry / rejection rate
stale-context delivery
handoff degradation
fault-recovery success
p95 end-to-end latency
hidden-test pass rate
```

## What ARC 0.11 does not claim yet

ARC 0.11 does **not** claim:

- B7 is better than B3/B5;
- a repository-scale benchmark has already been run;
- all providers expose trustworthy billing/token telemetry;
- retrieval/compile phase latency is already separately measured;
- stale-memory delivery can already be reconstructed perfectly for every historical baseline;
- the prototype B0/B2/B3/B5 implementations are already fair iso-budget competitors.

Those are experiment and baseline-normalization tasks, not facts to fill in by assumption.

The goal of 0.11 is to make the next empirical result difficult to accidentally fake.