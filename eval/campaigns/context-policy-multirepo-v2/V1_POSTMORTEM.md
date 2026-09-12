# V1 Postmortem

## Immutable campaign record

- Campaign: `context-policy-multirepo-v1`
- ARC frozen SHA: `85096e576e7dd3b38246ea0771b740698b582028`
- Attempt: `a001`
- Result: `FAILED`
- Failure location: Click `B5/r001/T001`, before candidate creation
- Forensic classification: `INSUFFICIENT_EVIDENCE_TO_EXCLUDE`
- Replacement: none; the frozen exclusions were not proven

Machine-readable status summary:

```text
campaign_status = FAILED
replacement_attempt = none
exclusion_status = unproven
scientific_result = unavailable
```

The attempt remains immutable and auditable. The preserved evidence shows that
the Codex child session was launched and that ARC received a generic failed
agent result, but it does not establish a completed first provider response,
a qualifying provider-side outage, or a host failure. No retry or replacement
attempt was authorized.

## Instrumentation gap

ARC persisted only `agent_status=failed` in the task failure event. The adapter
had more useful information available in memory, including the provider
summary, tool trace, token usage, cost, CLI return code, and redacted output
tails. The durable failure record therefore could not distinguish the provider
process launch boundary from a provider response boundary.

## Changes introduced for V2

V2 adds only general execution observability and apparatus qualification:

- sanitized structured provider failure diagnostics in durable events;
- direct provider return code, outcome, bounded redacted stdout/stderr tails,
  and explicit failure classification;
- observable provider lifecycle telemetry with `unknown` used where a plain
  text CLI cannot expose a boundary reliably;
- tolerant parsing of the documented `codex exec --json` JSONL lifecycle mode;
- deterministic fake-CLI tests for missing, non-zero, timeout, cancellation,
  redaction, empty-output, successful, and structured-event cases;
- `arc provider doctor` passive checks and an explicitly labelled isolated
  active smoke probe outside benchmark result directories.

The scientific design is intentionally unchanged: the same three repositories,
the same frozen repository commits, T001→T002→T003 sequences, B3/B5/B7
treatments, six repetitions, budgets, hidden graders, and hierarchical analysis
are proposed for V2.

## Scientific conclusion

V1 produced no comparative B3/B5/B7 result. The V1 failure is an apparatus
and execution record, not evidence for or against any scientific treatment,
context retrieval policy, task definition, repository choice, or statistical
procedure.
