# V12 capability map

## Existing capabilities retained

| Capability | Existing implementation | V12 disposition |
| --- | --- | --- |
| B3/B5/B7 manifests and progressive task order | `eval/campaigns/context-policy-multirepo-v12/` | Copy unchanged scientifically from V11; no observations imported |
| ARC execution, visible and hidden grading | `runtime/`, `eval/runners/`, `eval/grading/` | Reuse; no provider call during qualification |
| Docker, hidden-root, network and timeout qualification | V8 qualification scripts and pinned images | Reuse images and identities; regression only |
| Codex 0.133.0-alpha.1 / gpt-5.5 / high reasoning | V8 frozen runtime contract | Preserve exactly |

## V12 operational repairs

| Capability | New owner | Contract |
| --- | --- | --- |
| Atomic logical-task ledger | `production_state.py`, `execute_campaign.py`, `cli/study_commands.py` | Production path makes `logical_tasks` and `execution_instances` authoritative in one SQLite transaction |
| Provider-censor classification | `production_state.py` | Structured provider evidence precedes infrastructure, timeout, and model/agent classification |
| Bounded retry and resume | `production_state.py`, `execute_campaign.py` | One registered safe provider-censor retry; completed/model-failed/unsafe-censor tasks are not rerun |
| Task-level continuation | `production_state.py` | Model failure and provider censor remain task-level outcomes; legacy fail-fast is disabled |
| Integrated checkpoint | `production_state.py`, `eval/runners/experiment.py` | Checkpoint advances atomically with each durable logical-task transition |
| Measurement-gated scoring | `production_state.py` | Completed tasks require a durable measurement export/reference; campaign score requires all 162 |
| Provider-free regressions | `tests/test_context_policy_v12_operational_repair.py` | Deterministic fake provider path; real provider requests remain zero |

## Boundaries

- V11 source, preregistration, raw evidence, and results are historical and are not
  modified or copied into V12 result directories.
- This branch does not start `V12/a001` and does not authenticate or prompt a
  provider during validation.
- A provider-censored attempt is execution evidence, not a model failure.
