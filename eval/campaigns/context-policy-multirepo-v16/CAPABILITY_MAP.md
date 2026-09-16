# V16 capability map

## Existing capabilities retained

| Capability | Existing implementation | V16 disposition |
| --- | --- | --- |
| B3/B5/B7 manifests and progressive task order | `eval/campaigns/context-policy-multirepo-v16/` | Copy unchanged scientifically from V15; no observations imported |
| ARC execution, visible and hidden grading | `runtime/`, `eval/runners/`, `eval/grading/` | Reuse; no provider call during qualification |
| Docker, hidden-root, network and timeout qualification | V8 qualification scripts and pinned images | Reuse images and identities; regression only |
| Codex 0.133.0-alpha.1 / gpt-5.5 / high reasoning | V8 frozen runtime contract | Preserve exactly |

## V16 operational integration repair

| Capability | New owner | Contract |
| --- | --- | --- |
| Atomic logical-task ledger | `production_state.py`, `execute_campaign.py`, `cli/study_commands.py` | Production path makes `logical_tasks` and `execution_instances` authoritative in one SQLite transaction |
| Provider-censor classification | `production_state.py` | Structured provider evidence precedes infrastructure, timeout, and model/agent classification |
| Bounded retry and resume | `production_state.py`, `execute_campaign.py` | One registered safe provider-censor retry; completed/model-failed/unsafe-censor tasks are not rerun |
| Task-level continuation | `production_state.py` | Model failure and provider censor remain task-level outcomes; legacy fail-fast is disabled |
| Integrated checkpoint | `production_state.py`, `eval/runners/experiment.py` | Checkpoint advances atomically with each durable logical-task transition |
| Measurement-gated scoring | `production_state.py` | Completed tasks require a durable measurement export/reference; campaign score requires all 162 |
| Provider-free regressions | `tests/test_context_policy_v12_operational_repair.py` | Deterministic fake provider path; real provider requests remain zero |
| Attempt-scoped frozen profiles | `profile_staging.py`, `execute_campaign.py`, `cli/study_commands.py` | Qualification and production load the same immutable staged profile; ambient `.arc/config.yaml` is irrelevant |

## Boundaries

- V15 source, preregistration, raw evidence, and results are historical and are not
  modified or copied into V16 result directories.
- This branch does not start `V16/a001` and does not authenticate or prompt a
  provider during validation.
- A provider-censored attempt is execution evidence, not a model failure.
