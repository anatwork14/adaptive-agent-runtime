# ARC 0.12 Release Checklist

Milestone: **Normalized Context Baselines**

Target comparison: B3 static structured vs B5 naive vector top-k vs B7 provenance/version-aware ARC.

## Treatment normalization

- [x] `Orchestrator.execute_task` accepts an injectable context policy.
- [x] Production callers default to B7 when no policy is supplied.
- [x] B3/B5/B7 share leases, provider budget, worktree isolation, candidate creation, staleness detection, IntegrationGate, recovery, memory processing, hidden grading, and telemetry.
- [x] B3 retrieves no long-term memory.
- [x] B5 is fixed to deterministic `naive_vector_topk:k=5`.
- [x] B5 intentionally ignores temporal/supersession validity for selected memory.
- [x] B7 retains production provenance/version filtering.

## Budget/correctness contract

- [x] All policies receive the same declared hard token ceiling from the task/manifest.
- [x] All policies receive the same hard per-task USD ceiling.
- [x] Actual delivered context tokens are measured; exact iso-token equality is **not** claimed.
- [x] Same initial repo SHA and ordered task contract remain required by manifest validation.
- [x] Independent reset per baseline run is documented as mandatory.
- [x] Hidden tests remain after the normal IntegrationGate.

## Measurement

- [x] `context.policy_measured` records retrieval and compiler latency separately.
- [x] `context.compiled` records actual policy, hard budget, memory IDs, stale-memory IDs, and retrieval strategies.
- [x] `TaskMeasurement` records actual context policy and retrieval strategy IDs.
- [x] stale-memory delivery is directly measurable.
- [x] unknown provider cost/tokens remain nullable with coverage.
- [x] candidate SHA remains distinct from merged SHA.
- [x] context digest verifies against the final immutable packet.

## Reproducibility

- [x] B3/B5/B7 packaged example manifests share the same structural contract.
- [x] B5 strategy identifies `k=5` in telemetry.
- [x] B5 is documented as lexical-hash vector retrieval, not semantic embeddings.
- [x] ordered sequence semantics remain explicit.
- [ ] deterministic shared fault schedule — deferred beyond 0.12.
- [ ] automatic independent-reset benchmark provisioning — deferred beyond 0.12.
- [ ] provider sampling-seed enforcement — deferred beyond 0.12.
- [ ] B0/B2 normalization — deferred beyond 0.12.

## Tests

- [x] final ContextPacket digest regression.
- [x] B3 no-memory treatment regression.
- [x] B5 stale/superseded-memory delivery regression.
- [x] B7 stale-memory exclusion regression.
- [x] B3/B5/B7 same transactional execution-path integration test.
- [x] retrieval/compiler timing appears in task measurement.
- [x] normalized example manifests are pairwise comparable except for baseline.
- [ ] final Python 3.11 branch CI green.
- [ ] final Python 3.12 branch CI green.
- [ ] independent PR-triggered Python 3.11/3.12 CI green on frozen SHA.
- [ ] post-merge main CI green.
- [ ] Pages deployment green.

## Merge discipline

1. Freeze final branch SHA.
2. Confirm branch is `behind_by=0` against current `main`.
3. Open PR with frozen SHA in body.
4. Require independent pull-request-triggered CI on that exact SHA.
5. Squash merge with `expected_head_sha`.
6. Verify merged `main` CI and Pages before claiming release complete.
