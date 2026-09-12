# ARC 0.14 Release Checklist

## Repeated-study invariants

- [x] Repeated studies wrap the validated 0.13 isolated paired runner.
- [x] Every repetition starts from the same canonical repository commit.
- [x] Every treatment still receives fresh Git/ARC state and treatment-blinded provider context.
- [x] Agent adapter objects are fresh across the entire study, not only within one triplet.
- [x] Adapter fingerprint drift fails closed.
- [x] Source repository HEAD/files remain unchanged.
- [x] Disposable study workspaces are removed.

## Order control

- [x] Repeated studies use balanced crossover treatment ordering.
- [x] A complete cyclic block puts each baseline once in every ordinal position.
- [x] Alternate blocks reverse orientation.
- [x] The existing 0.13 seed-shuffle path remains the execution mechanism.
- [x] ARC deterministically selects seeds that realize the planned orders.
- [x] Actual treatment order is checked against the plan and divergence fails closed.
- [x] Scheduling seeds are not described as provider sampling seeds.

## Aggregate statistics

- [x] The paired repetition is the bootstrap sampling unit.
- [x] Resolved-rate delta is aggregated across repetitions.
- [x] Context-token delta is aggregated across repetitions.
- [x] Provider-token delta is aggregated only when both sides are observed.
- [x] Cost delta is aggregated only when both sides are observed.
- [x] p95 end-to-end latency delta is aggregated across repetitions.
- [x] Stale-delivery-rate delta is aggregated only when both sides are observed.
- [x] Every aggregate metric reports paired sample coverage.
- [x] Missing telemetry is never silently converted to zero.

## Provenance

- [x] Study/benchmark IDs and canonical repository commit are persisted.
- [x] Planned orders and realized manifest seeds are persisted.
- [x] Base-manifest SHA-256 digests are persisted.
- [x] Agent structural fingerprint is persisted without credentials.
- [x] ARC/Python/platform/Git runtime versions are persisted.
- [x] Gate/test/budget configuration is persisted.
- [x] CLI records provider/role/capability names without secret values.

## Operator surface

- [x] `arc benchmark paired` remains available.
- [x] `arc benchmark repeated` is added.
- [x] Repeated CLI defaults to 6 repetitions.
- [x] CLI exposes bootstrap sample count and CI mass.
- [x] CLI prints W/T/L, deltas, intervals, seeds, orders, and artifact directory.
- [x] CLI reuses fail-closed manifest/profile/model/provider-readiness validation.

## Validation

- [x] Deterministic integration smoke executes three complete B3/B5/B7 triplets.
- [x] Smoke proves balanced treatment position across a complete block.
- [x] Smoke proves nine distinct adapters for three repetitions.
- [x] Smoke proves aggregate artifacts and runtime provenance are emitted.
- [x] Regression test rejects adapter reuse across repetitions.
- [ ] Final feature-head CI green on Python 3.11 and 3.12.
- [ ] Independent PR-triggered CI green on exact frozen head.
- [ ] Branch is zero commits behind `main` before merge.
- [ ] Squash merge pinned to validated head SHA.
- [ ] Post-merge main CI and Pages green.

## Interpretation guardrail

A mock repeated study validates the apparatus only. Provider-backed repeated repository experiments are required before claiming that B3, B5, or B7 is empirically superior.
