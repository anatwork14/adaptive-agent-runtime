# V4 Postmortem — Closed Primary Attempt

## Disposition

- Campaign: `context-policy-multirepo-v4`
- Attempt: `a001`
- Status: `FAILED`
- Classification: `NON_EXCLUDABLE_FAILURE`
- Replacement under the frozen exclusions: `NO`
- `provider_execution_started`: `true`

The execution-boundary flag records that ARC created the durable V4 attempt
manifest and entered the repository run-plan phase. It does not establish that
the Codex provider process or a provider request started.

## Failure boundary

The preserved Click run-plan failed during nested execution-environment
validation. The preregistration required the dedicated provider identity, but
the nested `run-plan` process observed:

```text
provider_codex_home = None
provider_codex_config_path = None
provider_codex_config_sha256 = None
```

The failure occurred after the campaign crossed its execution boundary and
before a provider process was started. There is no evidence of a provider
process start, request start, response start, or provider completion.

## Scientific status

```text
candidate = none
task.submitted = none
visible gate = none
hidden grading = none
measurement = none
completed experimental cell = none
```

No B3/B5/B7 scientific conclusion is available from V4. The V4 attempt is
preserved exactly as produced and is not eligible for retry under its frozen
exclusions. V5 changes only the apparatus handoff that caused this failure.
