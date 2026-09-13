# V4 Timeout Audit

This audit distinguishes provider/agent execution from repository test
execution and orchestration subprocesses. The V4 scientific timeout change is
global and treatment-neutral: B3, B5, and B7 receive the same explicit
`provider_execution_timeout_seconds=600` value for every task and repetition.
There is no per-task override, per-repetition override, dynamic extension, or
retry on timeout.

| Source | File / function | Current value or source | Scope | Scientific relevance |
|---|---|---|---|---|
| Provider subprocess wait | `adapters/cli_process.py`, `SubprocessCodingAgent.run_prompt` | `AgentBudget.timeout_seconds`, frozen by V4 runtime contract as `600` | Global provider turn | The intended V4 change; a timeout is `CLI_TIMEOUT` with lifecycle, return code, bounded tails, configured limit, and elapsed time |
| Benchmark agent budget | `runtime/orchestrator.py`, `Orchestrator.execute_task` | `provider_execution_timeout_seconds`, supplied by paired runner from the frozen plan | B3/B5/B7, all tasks/repetitions | Binds the preregistered value to the actual provider invocation |
| Persistent session budget | `application/sessions.py`, worker-turn budget construction | Repository `ArcConfig.provider_execution_timeout_seconds`, default `180`, V4 freeze sets `600` | Non-benchmark sessions using the same config | Keeps the application session path consistent without changing the V3 default |
| Docker visible tests | `isolation/container.py`, `SandboxRunner.run`; repository harness | Frozen per-repository harness value `180` | Visible G2 gate | Preserved; not the provider timeout |
| Docker hidden tests | `isolation/container.py`, `SandboxRunner.run`; repository harness hidden command | Same frozen harness timeout `180` | Task-scoped hidden grading | Preserved; not the provider timeout |
| Campaign run-plan subprocess | V4 `execute_campaign.py`, `_run_logged` | No campaign-level timeout; process is waited to completion | Study orchestration | No scientific timeout change; failures remain durable and non-retried |
| Meta-analysis subprocess | V4 `execute_campaign.py`, `_run_logged` | No meta timeout; process is waited to completion | Offline aggregation | No provider inference and no scientific timeout change |
| Git subprocesses | `isolation/worktree.py`, `runtime/git.py`, campaign helpers | No generic subprocess timeout; ARC writes use hermetic command/env settings | Candidate and integration plumbing | Not the V4 variable; Git errors remain apparatus failures and are never retried implicitly |
| Provider CLI version probe | `eval/.../runtime_lock.py` | Command-specific version check; frozen CLI `codex-cli 0.133.0-alpha.1` | Freeze/preflight only | Not benchmark inference |
| Provider active smoke | `application/provider_doctor.py`, `run_provider_probe` | V4 qualification invokes it with explicit `600`; it remains a disposable non-benchmark probe | Non-benchmark qualification only | Scientific evidence is false; it cannot create a benchmark measurement |

## Diagnostic contract

Every provider timeout must preserve:

- `failure_classification=CLI_TIMEOUT`;
- `provider_outcome=timeout`;
- `configured_timeout_seconds=600`;
- the subprocess return code when observable;
- lifecycle state, including request/response boundaries when observed;
- bounded redacted stdout/stderr tails; and
- non-negative elapsed duration.

No timeout path fabricates a completed turn, candidate commit, gate result,
hidden grade, or measurement. A timeout never triggers an automatic retry.
