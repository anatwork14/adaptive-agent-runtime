# ARC 0.14 — Repeated Paired Trials

ARC 0.14 extends the reset-safe, treatment-blinded paired runner from 0.13 into a repeated-study harness suitable for provider-backed experiments.

## Why repeated trials are necessary

One B3/B5/B7 triplet is an experimental unit, not a paper result. External coding agents can vary across calls because of provider sampling, backend changes, transient tool behavior, and repository interaction. Tasks inside one run also share one evolving Git trajectory, event log, and memory history, so treating each task row as an independent statistical sample would understate uncertainty.

ARC 0.14 therefore uses the **paired repetition** as the sampling unit. Every repetition keeps repository commit, task contract, profile/model, budgets, gate, and hidden-test contract fixed, then executes isolated B3/B5/B7 trajectories and produces one summary per baseline.

## Balanced crossover scheduling

Standalone `arc benchmark paired` retains the 0.13 seed-shuffled treatment order.

Repeated studies use a stronger schedule. ARC constructs cyclic crossover blocks so that, for a complete block, every baseline appears exactly once in every ordinal position. Alternate blocks reverse orientation. For three baselines, a six-repetition study covers both crossover orientations and all six possible treatment orders.

The repeated runner does not bypass the validated 0.13 path. Instead it deterministically finds manifest seed values whose existing v0.13 shuffle produces the planned balanced order, then checks the actual order after execution. Any divergence fails closed.

The recorded seed is therefore scheduling metadata. It is not a claim that an external provider uses the same value for token sampling.

## Statistical unit and metrics

For each baseline pair A/B, ARC computes one delta per repetition:

```text
delta_r = summary_A,r - summary_B,r
```

It then bootstraps those repetition-level deltas. Current aggregate metrics are resolved-rate delta, mean delivered context-token delta, mean observed provider-token delta, mean observed cost delta, p95 end-to-end latency delta, and stale-delivery-rate delta.

Positive values mean **baseline A > baseline B** for the named pair. Nullable telemetry remains nullable: if one side of a repetition lacks an observed metric, that repetition is excluded for that metric only, and `sample_count` reports the actual paired coverage.

ARC does not currently emit a p-value or equate a confidence interval with a complete hypothesis test.

## Fresh-agent invariant

The 0.13 paired runner requires a fresh adapter object for every treatment inside one triplet. 0.14 extends that invariant across the complete repeated study. Reusing an adapter object in a later repetition fails closed, and ARC retains references to created adapters until study completion so object identity cannot be accidentally recycled.

Adapter fingerprints must also remain stable. The non-secret fingerprint records adapter type, name, provider identifier when exposed, model name when exposed, and executable name when exposed.

## Runtime provenance

Each study writes `provenance.json` with the canonical repository commit, original base seed, balanced order schedule, planned orders, realized manifest seeds, repetition count, bootstrap settings, agent profile/model, adapter fingerprint, SHA-256 digests of the base manifests, ARC/Python/platform/Git versions, gate/test/budget configuration, and caller-supplied non-secret metadata.

This cannot fingerprint opaque provider backend revisions that the provider does not expose; those remain an external experimental limitation.

## CLI

```bash
arc benchmark repeated \
  b3.yaml b5.yaml b7.yaml \
  --repo . \
  --repeats 6 \
  --bootstrap-samples 2000 \
  --ci 0.95 \
  --hidden-test-dir /secure/hidden-tests
```

For three baselines, `--repeats 6` is the default because it covers both crossover orientations. The command reuses the same fail-closed profile/model/provider-readiness validation as `arc benchmark paired`.

## Study artifacts

The study root is:

```text
<output>/<benchmark_id>/studies/<study_id>/
```

It contains `study.json`, `provenance.json`, `aggregates.json`, and a `repeats/` subtree. Each repetition is a complete 0.13 paired-run artifact tree with manifests, measurements, summaries, events, authoritative state DB, derived memory DB, and final Git heads. Failures write `failure.json`; disposable workspaces are removed.

## Interpreting the aggregate table

The CLI reports pair orientation, repetition-level W/T/L counts, mean deltas, bootstrap intervals, coverage, realized orders, seeds, and artifact directory. W/T/L is based on each repetition's resolved-rate delta and is descriptive rather than a substitute for task-level error analysis.

## Minimum evidence discipline

A deterministic mock repeated study validates the apparatus only. For an empirical B3/B5/B7 claim: use a real provider-backed coding agent; keep repository/task/profile/model/budget/test/gate fixed; use enough repetitions for the expected variance; inspect coverage; retain provenance and every trace; report failures and rejected candidates; predeclare exclusions; and avoid claiming provider-output determinism unless the provider exposes and honors a sampling seed.

## Next research milestones

After 0.14, the highest-value work is repository-scale provider-backed studies, context-pressure and stale-memory interventions, deterministic handoff/fault schedules, cost/latency effect-size analysis, and hierarchical analysis when experiments span multiple repositories.
