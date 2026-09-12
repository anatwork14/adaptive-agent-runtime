# V2 Provider Observability Design

## Durable failure record

When an agent does not complete, ARC writes both a `provider.failed` event and
a `task.failed` event containing the same sanitized diagnostic subset:

- `agent_status`, `agent_summary`, `tool_trace`, `token_usage`, and `cost_usd`;
- `failure_classification`;
- `provider_returncode` and `provider_outcome`;
- bounded `stdout_tail` and `stderr_tail`;
- `provider_lifecycle` and observed `provider_events`.

The event path applies key-based redaction, command redaction, and provider
token-pattern redaction. Environment values are never included; only approved
environment-key metadata is retained.

## Classification

The classifier is evidence-first and conservative. It distinguishes:

`CLI_NOT_FOUND`, `CLI_NONZERO_EXIT`, `CLI_TIMEOUT`, `CLI_CANCELLED`,
`AUTH_FAILURE`, `PROVIDER_SERVICE_ERROR`, `NETWORK_ERROR`,
`CONFIGURATION_ERROR`, and `UNKNOWN_PROVIDER_FAILURE`.

Classification is secondary to the raw bounded evidence. Ambiguous failures
remain `UNKNOWN_PROVIDER_FAILURE` rather than being promoted to a provider or
host attribution.

## Lifecycle boundaries

The subprocess adapter records `provider.process_started` after successful
process creation and `provider.request_started` after the prompt is accepted by
stdin. Plain text output does not prove a model response, so
`response_started` remains `unknown` unless a provider adapter can observe it
from a documented structured event. Completion, failure, timeout, and
cancellation are recorded from the subprocess outcome.

Codex V2 may use the CLI-documented `codex exec --json` JSONL mode. ARC parses
only known lifecycle event types and ignores unknown/malformed lines. It stores
the lifecycle names, not raw structured event payloads, to avoid turning model
or tool content into an additional durable copy.

## Qualification boundary

`arc provider doctor` has two intentionally separate modes:

- passive: executable, version, authentication state where supported, effective
  redacted argv, model, role, and environment-key metadata;
- active: one explicit minimal non-benchmark prompt in a disposable git
  workspace, with a timestamped JSON result outside benchmark result trees.

The active result is labelled `scientific_evidence=false` and
`benchmark_context=false`. It is a qualification artifact only and cannot enter
the V2 result or analysis directories.
