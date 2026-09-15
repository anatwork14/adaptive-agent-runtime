# V9 capability map

## Existing capabilities retained

| Capability | Existing implementation | V9 disposition |
| --- | --- | --- |
| B3/B5/B7 manifests and progressive task order | `eval/campaigns/context-policy-multirepo-v8/` | Copy unchanged scientifically; only campaign identity changes |
| ARC execution, visible and hidden grading | `runtime/`, `eval/runners/`, `eval/grading/` | Reuse; no provider call during qualification |
| Docker, hidden-root, network and timeout qualification | V8 qualification scripts and pinned images | Reuse images and identities; regression only |
| Codex 0.133.0-alpha.1 / gpt-5.5 / high reasoning | V8 frozen runtime contract | Preserve exactly |

## New V9 capabilities

| Capability | New owner | Contract |
| --- | --- | --- |
| Atomic logical-task ledger | `attempt_state.py` | SQLite transaction per state transition; append-only execution instances |
| Provider-censor classification | `attempt_state.py` | Explicit machine-readable reason; no inference from exit code alone |
| Bounded retry and resume | `attempt_state.py`, `execute_campaign.py` | One registered provider-censor retry; completed/model-failed tasks are not rerun |
| Completeness-gated scoring | `attempt_state.py` | Completed task metrics are immediate; aggregate/final score requires all required tasks completed |
| Provider-free regressions | `run_provider_censor_regressions.py` | Deterministic fake provider; zero provider requests |

## Boundaries

- V8 source, preregistration, raw evidence, and results are historical and are not
  modified or copied into V9 result directories.
- This branch does not start `V9/a001` and does not authenticate or prompt a
  provider during validation.
- A provider-censored attempt is execution evidence, not a model failure.
