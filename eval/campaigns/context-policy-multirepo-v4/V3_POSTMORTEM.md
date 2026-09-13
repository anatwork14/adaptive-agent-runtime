# V3 Postmortem — Closed Primary Attempt

## Disposition

- Campaign: `context-policy-multirepo-v3`
- Attempt: `a001`
- Status: `FAILED`
- Classification: `NON_EXCLUDABLE_FAILURE`
- Replacement under the frozen exclusions: `NO`
- `provider_execution_started`: `true`

The preserved V3 result tree is `/Users/teobun/arc-study/results/context-policy-multirepo-v3/a001`.
It must not be rerun, overwritten, finalized, or used to create a V3/a002
attempt. The preserved forensic bundle remains the audit record.

## Failure boundary

The failed cell was B3 / r001 / seed20260915 / T001 in Click. The durable ARC
events show context compilation, then provider process start, prompt write,
provider request start, and provider response start. The provider process was
terminated with return code `-15` after the configured 180-second limit. ARC
classified the result as `CLI_TIMEOUT` and recorded no provider token usage,
candidate submission, visible gate, hidden grading, or measurement for that
failed cell.

The matching Codex session contains agent/tool activity but no authoritative
completion record. The durable ARC event store is authoritative for the
execution boundary. The evidence supports a provider-side timeout after the
first provider turn began; it does not support a provider outage or host
failure before the first provider turn.

## Scientific status

V3 produced no valid complete comparative B3/B5/B7 campaign result. The
partial B5 artifacts that precede the failed B3 cell are retained as apparatus
evidence only. They are not evidence for or against B5, do not complete a
paired B5 comparison, and must not be interpreted as a treatment result.

V4 preserves the V3 repository commits, task sequence, hidden-test contract,
treatments, repetition schedule, budgets, provider/model, reasoning setting,
Docker identities, and verification contract. Its sole protocol change is the
explicit provider/agent execution timeout, changed from `180` to `600` seconds
for B3, B5, and B7 alike.
