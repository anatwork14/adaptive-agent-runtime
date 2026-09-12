# ARC 0.13 Release Checklist

## Core paired-run invariants

- [x] B3/B5/B7 share the normalized ARC execution/gate path from 0.12.
- [x] Each treatment starts from the same canonical Git commit.
- [x] Each treatment receives a fresh authoritative EventStore.
- [x] Each treatment receives a fresh derived memory database.
- [x] Project constraints and the complete ordered task contract are materialized from the manifest.
- [x] Dependencies must reference earlier tasks in the sequence.
- [x] Duplicate task IDs fail closed.
- [x] The source repository HEAD and working tree are not mutated by the paired runner.
- [x] Treatment order is deterministically seed-shuffled.
- [x] Treatment workspace paths use opaque names rather than baseline labels.
- [x] A fresh agent-adapter object is required for every treatment.
- [x] Agent adapter type/name drift fails closed.
- [x] Provider-visible ContextPackets blind treatment/audit metadata while preserving semantic context.
- [x] Disposable integration/task/gate runtime workspaces are cleaned up.
- [x] Event/memory/result artifacts remain available after cleanup.
- [x] Pairwise comparison summaries are produced from the isolated result sets.

## Comparability contract

- [x] Generic comparability checks project constraints.
- [x] Generic comparability checks task type/capabilities/dependencies/symbols.
- [x] `benchmark_id` remains a result namespace rather than a generic treatment field.
- [x] Automatic paired execution requires one shared benchmark ID.
- [x] Explicit `hard_task_usd` is required for automatic paired execution.
- [x] Unsupported B0/B2 treatments continue to fail closed.
- [x] Fault-enabled manifests continue to fail closed until scheduling is normalized.

## Operator surface

- [x] `arc benchmark paired ...` is isolated in a dedicated Typer sub-app.
- [x] The installed entrypoint preserves no-argument interactive-shell behavior.
- [x] CLI verifies one configured agent profile across manifests.
- [x] CLI verifies one declared model and equality with the configured profile model.
- [x] CLI requires the selected profile to pass provider doctor readiness.
- [x] CLI prints baseline outcomes, execution order, and persistent artifact directory.

## Validation

- [x] Unit tests cover dependency ordering and treatment blinding.
- [x] Existing manifest-comparison behavior remains backward compatible.
- [x] Integration smoke test executes isolated B3/B5/B7 trajectories with fresh adapters.
- [x] Smoke test proves source repository immutability.
- [x] Smoke test proves first-task event-version reset equality.
- [x] Smoke test proves B3 memory omission vs B5/B7 memory availability on a later task.
- [x] Smoke test proves runtime cleanup and persistent audit artifacts.
- [ ] Final branch Python 3.11 CI passes.
- [ ] Final branch Python 3.12 CI passes.
- [ ] Independent pull-request CI passes on frozen head.
- [ ] Branch remains 0 commits behind `main` before merge.
- [ ] Head-pinned squash merge succeeds.
- [ ] Post-merge Python 3.11/3.12 CI passes on `main`.
- [ ] Pages deployment succeeds on merged `main`.

## Interpretation guardrails

- [x] Documentation states that mock results validate apparatus only.
- [x] Documentation distinguishes deterministic treatment order from provider-output determinism.
- [x] Documentation retains matched-hard-ceiling vs exact-iso-token distinction.
- [x] Documentation states B5 is lexical-hash vector top-k, not a semantic embedding baseline.
- [x] Documentation states one paired triplet is insufficient for paper-level empirical claims.
