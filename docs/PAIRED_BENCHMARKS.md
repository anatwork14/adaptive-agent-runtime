# ARC 0.13 — Isolated Paired Benchmarks

ARC 0.13 turns the normalized B3/B5/B7 context policies from ARC 0.12 into an automatically reset paired experiment.

## Goal

A valid paired comparison must change the context policy without quietly changing the repository base, ARC state, agent profile/model, task contract, hard budgets, gate settings, or hidden-test contract.

The runner therefore creates an independent experimental trajectory for every treatment:

```text
same manifest contract + same canonical Git commit
                    |
        seed-shuffled execution order
                    |
       +------------+------------+
       |            |            |
      B3           B5           B7
       |            |            |
 detached WT   detached WT   detached WT
 fresh events  fresh events  fresh events
 fresh memory  fresh memory  fresh memory
 fresh agent   fresh agent   fresh agent
       |            |            |
  standard Orchestrator / candidate / IntegrationGate
       |            |            |
  measurements + events + state + memory artifacts
       +------------+------------+
                    |
             paired comparisons
```

Baselines run sequentially. ARC task worktrees use Git refs such as `arc/task/T001`, so sequential treatment execution avoids branch-ref collisions while still providing independent integration worktrees and databases.

## Experimental isolation

For each baseline ARC creates:

- a detached integration worktree at the manifest's canonical `repo_commit`;
- a fresh authoritative `EventStore`;
- a fresh derived memory SQLite database;
- the same project constraints and ordered task DAG materialized from the manifest;
- a fresh agent-adapter object from the caller's factory;
- the same provider/token/USD/gate configuration;
- a separate result directory.

The source repository's working tree and HEAD are not mutated by a paired run.

After one treatment finishes, its disposable integration worktree and per-workspace `.arc-runtime` worktree/gate scaffolding are removed. Audit artifacts are retained separately.

## Treatment blinding

Real coding-agent adapters serialize `ContextPacket` into the provider prompt. ARC 0.12 packets contain useful audit metadata such as:

- `context_policy`;
- `memory_ids`;
- `stale_memory_ids`;
- `retrieval_strategies`;
- event/version IDs;
- leases/fencing tokens;
- digest and risk flags.

Showing these values to the model would leak the experimental treatment. ARC 0.13 therefore wraps provider adapters with `BlindedAgentAdapter` during paired studies.

The wrapper preserves the actionable semantic content—goal, constraints, acceptance criteria, dependencies, code evidence, and memory text—but removes/normalizes treatment and operational metadata before the provider sees it. The original packet and true treatment remain available to ARC's event/measurement plane.

This means the model can benefit or suffer from the *content selected by the policy* without being told `B3`, `B5`, or `B7`.

## Manifest contract

ARC 0.13 extends `EvaluationTaskSpec` with:

- `task_type`;
- `required_capabilities`;
- `dependencies`;
- `symbols`.

`BenchmarkManifest` additionally records `project_constraints`.

Dependencies must refer to earlier tasks in the ordered sequence. Duplicate task IDs are rejected.

Generic `validate_comparable_manifests()` treats `benchmark_id` as a result namespace rather than a treatment field for backward compatibility. `IsolatedPairedBenchmarkRunner`, however, requires all manifests in one automatic paired run to share one `benchmark_id` so their artifacts live under one auditable run namespace.

## Execution order

Treatment order is shuffled deterministically using the manifest seed. Workspace names are opaque (`w01-...`, `w02-...`) and do not contain `b3`, `b5`, or `b7`.

This reduces avoidable treatment-order and path-label leakage. It does not make an external provider deterministic. If the provider cannot enforce a sampling seed, `seed` is experiment scheduling metadata rather than a claim of model-output determinism.

## Python API

```python
from application.agents import build_agent
from application.config import ConfigStore
from eval import IsolatedPairedBenchmarkRunner, load_manifest

manifests = [
    load_manifest("b3.yaml"),
    load_manifest("b5.yaml"),
    load_manifest("b7.yaml"),
]

config = ConfigStore(".").load()
profile = config.agents[manifests[0].agent_profile]

runner = IsolatedPairedBenchmarkRunner(
    ".",
    visible_test_cmd=config.visible_test_cmd or None,
    hard_project_usd=config.hard_project_usd,
    hidden_test_dir="/secure/hidden-tests",
)

result = await runner.run(
    manifests,
    lambda: build_agent(profile),
)
```

The factory must return a fresh adapter object for every treatment. ARC rejects reuse of the same object and rejects adapter type/name drift across the paired run.

## CLI

ARC 0.13 adds:

```bash
arc benchmark paired \
  b3.yaml b5.yaml b7.yaml \
  --repo . \
  --hidden-test-dir /secure/hidden-tests
```

The CLI additionally verifies that all manifests declare one configured `agent_profile`, that they declare one model, and that the manifest model matches that configured profile before execution. The selected profile must pass ARC's provider doctor check.

Persistent results default outside the source repository under `.arc-benchmark-results/<repo>/...`. Disposable workspaces default under `.arc-benchmark-runtime/<repo>/...`.

## Audit artifacts

Each baseline directory contains:

```text
manifest.json
measurements.jsonl
summary.json
events.jsonl
state.db
memory.db
final_head.txt
```

The paired-run root additionally contains `paired_run.json` with:

- canonical base commit;
- seed-shuffled execution order;
- per-treatment final commits and event counts;
- pairwise comparison summaries.

If a treatment fails, ARC writes `failure.json` before propagating the error.

## What the smoke benchmark proves

The deterministic mock integration test proves the *apparatus*:

- all treatments start from one Git commit;
- source HEAD/files remain unchanged;
- first-task authoritative event versions match;
- event/memory databases are independent;
- provider-visible treatment labels are blinded;
- B3 does not receive prior durable memory while B5/B7 can;
- disposable workspaces are cleaned up;
- persistent audit artifacts survive;
- pairwise comparisons can be computed.

Mock-agent outcomes are **not evidence that one context policy is better**.

## Remaining limits before empirical claims

ARC 0.13 still does not claim:

- exact iso-token delivery (v0.12 matches hard ceilings and records delivered tokens);
- semantic embeddings for B5 (it remains deterministic lexical-hash vector top-k);
- deterministic model outputs for providers without seed controls;
- normalized B0/B2 execution;
- deterministic fault scheduling;
- enough statistical power from one paired triplet.

The next empirical phase should run multiple provider-backed paired repetitions over repository-scale ordered task sequences, then aggregate paired outcomes with confidence intervals and ablations.
