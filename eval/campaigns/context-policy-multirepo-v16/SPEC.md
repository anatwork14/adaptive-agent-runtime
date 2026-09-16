# Context-policy multirepo V16 specification

## Objective

V16 preserves the V15 scientific comparison and provider-side fault handling. The
scientific hypothesis, treatments, task order, baselines, repetitions, model,
reasoning setting, Codex build, Docker images, hidden tests, timeouts, sandbox,
and network isolation are unchanged. V16 makes two operational corrections at
the production CLI boundary: dynamic production-state modules are registered in
`sys.modules` before execution, and the campaign selector maps each supported
campaign explicitly and rejects unknown campaigns. The production path still
classifies structured provider evidence, persists its authoritative logical-task
ledger, continues after task-level failures, and updates an integrated
checkpoint after every durable transition. Codex invocations still stage exact
bytes from the campaign-owned immutable snapshot into a disposable
per-provider-turn `CODEX_HOME`; authentication remains runtime-only.

The observation key is `(repository, repetition, baseline, task)`. Every key has
an independent persisted state and one or more append-only execution instances.

## State and evidence

Logical states are `PENDING`, `RUNNING`, `COMPLETED`, `PROVIDER_CENSORED`,
`TIMEOUT`, `MODEL_FAILED`, and `INFRASTRUCTURE_FAILED`. `execution_status` is
separate from `scientific_status`: a failed provider execution is scientifically
`CENSORED`, not a model failure.

Each execution instance persists atomically with its logical-task transition:
identity, provider lifecycle flags, provider failure class, CLI exit, usable
output, tool execution, workspace mutation, token usage, terminal
classification, raw-evidence reference, measurement reference, and retry
eligibility. Completed instances are immutable. The same SQLite transaction
updates `logical_tasks`, terminalizes the instance, and advances the integrated
checkpoint; filesystem state and event streams are not authorities.

`PROVIDER_CENSORED` requires explicit evidence of an external provider failure:
usage/quota limit, rate limit, provider 5xx/service unavailability,
authentication/session-service failure, or transport interruption before usable
output. A nonzero process exit, failed test, bad code, tool misuse, or agent
context mistake is not sufficient. Provider evidence has precedence over
infrastructure, timeout, and model/agent classifications. Safe automatic retry requires all three
explicit booleans to be false: no usable model output, no tool execution, and
no workspace mutation.

## Retry, continuation, and resume

`max_provider_censor_retries_per_logical_task = 1`. A retry is a new registered
execution instance with a fresh task session and identical frozen task input;
the censored instance is never overwritten. The runner never retries a known
exhausted quota without independent provider availability confirmation. No
sacrificial prompt is allowed. Completed tasks are skipped on resume;
provider-censored tasks follow the bound and availability gate; model failures
are preserved and the next schedulable task is evaluated; timeouts retain frozen
timeout semantics; infrastructure defects, contract corruption, ledger
corruption, and sandbox-integrity failures stop the campaign. The legacy
run-level fail-fast behavior is not permitted for task-level model or provider
censor outcomes.

## Scoring

Completed-task metrics are available immediately only after a durable
measurement export/reference exists. Baseline/repetition aggregates
and the campaign score are withheld unless every required logical task is
`COMPLETED`. Provider-censored observations are missing under this explicit
policy and are never scored as model failures.

## V15 closure boundary

V15 is permanently closed as `PRE_EXECUTION_PRODUCTION_CLI_INTEGRATION_INVALIDATED`.
It has zero observations and zero provider requests. V16 starts with zero
observations and imports no V15 ledger, measurement, event, or score.

## V16 operational boundary

Qualification and production use the same direct-Python launcher and qualified
`.venv`; no project-resolving `uv run` process may write into the persistent ARC
source repository. The launcher identity is frozen and source cleanliness is
checked after startup, preflight, profile staging, qualification, and boundary
initialization. The V15 attempt-scoped profile staging path remains unchanged.

## Validation and freeze

Provider-free tests cover launcher containment, classification, atomic persistence, checkpoint/resume,
retry bounds and gating, immutability, scoring completeness, Docker isolation,
hidden-root isolation, network isolation, timeout/cancellation, preregistration
round-trip, cross-artifact parity, immutable snapshot identity, ambient-config
independence, and temporary preflight. V16 is frozen exactly once; after the
freeze directory is written it is not patched or resealed. Validation stops
before provider execution.
