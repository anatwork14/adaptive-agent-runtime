# ARC 0.11 Release Checklist — Research Evaluation Harness

ARC 0.11 is ready only when the evaluation layer cannot silently manufacture a stronger result than the runtime actually observed.

## Measurement integrity

- [ ] no fixed placeholder cost is emitted by `ExperimentRunner`;
- [ ] no fixed placeholder provider-token count is emitted;
- [ ] end-to-end task duration is not labeled retrieval latency;
- [ ] unavailable cost/token telemetry is serialized as `null`;
- [ ] summaries report cost/token measurement coverage;
- [ ] context tokens come from `context.compiled` events;
- [ ] gate outcome comes from the normal `IntegrationGate` result;
- [ ] event interval and candidate SHA remain attached to every measurement;
- [ ] optional hidden tests run only after normal ARC integration;
- [ ] hidden-test absence is represented as unknown, not passed.

## Reproducibility

- [ ] JSON/YAML manifests validate through one schema;
- [ ] every task matches the manifest context-token budget;
- [ ] fault declarations are part of the manifest;
- [ ] repo commit, agent, model, seed, task contract and budgets are recorded;
- [ ] task rows round-trip through canonical JSONL;
- [ ] summaries serialize to stable JSON;
- [ ] paired comparison rejects mismatched repository commits;
- [ ] paired comparison rejects mismatched token/USD budgets;
- [ ] paired comparison rejects different models/agents/seeds/fault schedules;
- [ ] paired comparison rejects changed task correctness contracts.

## Baseline safety

- [ ] B7 trace-derived execution is supported;
- [ ] runner rejects B0/B2/B3/B5 as comparable until their shared gate/budget interface is normalized;
- [ ] documentation explicitly states no B7 superiority result exists yet;
- [ ] all future baselines must use the same exact-candidate IntegrationGate and hidden-test contract.

## Tests

- [ ] zero-valued historical provider telemetry remains unknown;
- [ ] positive observed usage aggregates correctly;
- [ ] matched-budget manifest validation passes/fails deterministically;
- [ ] summary coverage and null behavior are tested;
- [ ] manifest/result IO round trips are tested;
- [ ] paired task comparison is tested;
- [ ] existing runtime, security, live-turn, gate and memory tests remain green.

## Release verification

- [ ] package version is `0.11.0`;
- [ ] exact branch head passes Python 3.11 CI;
- [ ] exact branch head passes Python 3.12 CI;
- [ ] Ruff correctness checks pass;
- [ ] browser JavaScript syntax checks pass;
- [ ] complete pytest suite passes;
- [ ] package build succeeds;
- [ ] branch is `behind_by=0` immediately before PR freeze;
- [ ] independent pull-request-triggered CI passes the frozen head;
- [ ] squash merge uses `expected_head_sha`;
- [ ] merged `main` passes Python 3.11/3.12 CI;
- [ ] Pages deploy succeeds.

## Explicit non-claims

ARC 0.11 does not claim that B7 outperforms B3/B5, that repository-scale experiments are complete, or that every provider exposes trustworthy token/cost telemetry. It establishes the measurement contract required to test those claims next.
