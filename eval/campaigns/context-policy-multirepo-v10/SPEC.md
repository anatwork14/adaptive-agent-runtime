# Context-policy multirepo V10 specification

## Objective

V10 preserves the V9 scientific comparison and provider-side fault handling. The
scientific hypothesis, treatments, task order, baselines, repetitions, model,
reasoning setting, Codex build, Docker images, hidden tests, timeouts, sandbox,
and network isolation are unchanged. The sole change is operational: Codex
invocations stage exact bytes from the campaign-owned immutable snapshot into a
disposable per-provider-turn `CODEX_HOME`; authentication remains runtime-only.

The observation key is `(repository, repetition, baseline, task)`. Every key has
an independent persisted state and one or more append-only execution instances.

## State and evidence

Logical states are `PENDING`, `RUNNING`, `COMPLETED`, `PROVIDER_CENSORED`,
`TIMEOUT`, `MODEL_FAILED`, and `INFRASTRUCTURE_FAILED`. `execution_status` is
separate from `scientific_status`: a failed provider execution is scientifically
`CENSORED`, not a model failure.

Each execution instance persists atomically after the task transition:
identity, provider start/end, model, prompt/config identity, provider status and
machine-readable reason, token usage, agent terminal state, patch/commit,
visible and hidden evaluation, score components, artifact hashes, and retry
eligibility. Completed instances are immutable.

`PROVIDER_CENSORED` requires explicit evidence of an external provider failure:
usage/quota limit, rate limit, provider 5xx/service unavailability,
authentication/session-service failure, or transport interruption before usable
output. A nonzero process exit, failed test, bad code, tool misuse, or agent
context mistake is not sufficient. Safe automatic retry requires all three
explicit booleans to be false: no usable model output, no tool execution, and
no workspace mutation.

## Retry and resume

`max_provider_censor_retries_per_logical_task = 1`. A retry is a new registered
execution instance with a fresh task session and identical frozen task input;
the censored instance is never overwritten. The runner never retries a known
exhausted quota without independent provider availability confirmation. No
sacrificial prompt is allowed. Completed tasks are skipped on resume;
provider-censored tasks follow the bound and availability gate; model failures
are preserved; timeouts retain frozen timeout semantics; infrastructure defects
stop the campaign.

## Scoring

Completed-task metrics are available immediately. Baseline/repetition aggregates
and the campaign score are withheld unless every required logical task is
`COMPLETED`. Provider-censored observations are missing under this explicit
policy and are never scored as model failures.

## Validation and freeze

Provider-free tests cover classification, atomic persistence, checkpoint/resume,
retry bounds and gating, immutability, scoring completeness, Docker isolation,
hidden-root isolation, network isolation, timeout/cancellation, preregistration
round-trip, cross-artifact parity, immutable snapshot identity, ambient-config
independence, and temporary preflight. V10 is frozen exactly once; after the
freeze directory is written it is not patched or resealed. Validation stops
before provider execution.
