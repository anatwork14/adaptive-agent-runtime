# ARC 0.10 Release Checklist — Supervised Live Turns

ARC 0.10 is ready to merge only when the exact candidate head satisfies every gate below.

## Scope

The release adds one product capability without changing ARC's correctness boundary:

```text
browser instruction
      ↓
TURN_<id>
      ↓
disposable provider process
      ↓
redacted streamed output + explicit cancellation
      ↓
isolated worker worktree
      ↓
explicit submit
      ↓
exact Git candidate
      ↓
IntegrationGate
```

Provider output/process state remains operational. Task/Git/gate facts remain authoritative.

## Functional gates

- [ ] `POST /api/sessions/{session}/turn` returns `202` without waiting for provider exit.
- [ ] each browser turn receives a stable `TURN_*` identifier.
- [ ] stdout/stderr is emitted incrementally as `session.turn_output`.
- [ ] Workspace renders live output through the existing `/ws/events` channel.
- [ ] `POST /api/sessions/{session}/turn/cancel` records cancellation intent and terminates the provider.
- [ ] cancelled turns return the `WorkerSession` to `OPEN` and are never recorded as successful completion.
- [ ] active live turns hold the shared per-worker action lock.
- [ ] submit/review/runtime mutations cannot race an active live turn.
- [ ] worker Stop cancels/waits for the supervised turn before removing its worktree.
- [ ] Workspace shutdown requests cleanup for active live turns.
- [ ] legacy blocking `/messages` and scriptable `arc session send` remain compatible.

## Security gates

- [ ] provider child still receives the ARC 0.9 least-privilege execution environment.
- [ ] provider-to-provider environment credential separation remains intact.
- [ ] credential-like forwarded environment values are redacted before streamed output persistence.
- [ ] common `sk-*`, `sess-*`, `ya29.*`, and Bearer token shapes are redacted.
- [ ] final stdout summaries and stderr failure summaries use redacted text.
- [ ] live output uses text rendering in the Workspace rather than HTML injection.
- [ ] 0.9.1 strict loopback bind and HTTP/WebSocket Origin protections remain intact.
- [ ] provider processes are still documented as host-mode/non-sandboxed.
- [ ] output redaction is documented as defense in depth, not complete DLP.

## Deterministic tests

- [ ] output callback observes provider output before process exit.
- [ ] a long-running provider turn is cancelled before its normal timeout.
- [ ] a pre-cancelled turn never launches its provider process.
- [ ] test credential text is absent from streamed output and final summary.
- [ ] asynchronous Workspace turn start/status/cancel flow passes.
- [ ] submit returns `409` while a live turn owns the worker lock.
- [ ] stop-live-turn integration proves worktree removal occurs after cancellation.
- [ ] existing worker/session/review/runtime/security tests remain green.
- [ ] browser version regression checks installed distribution metadata rather than a frozen historical version.

## Release verification

- [ ] branch is based on the current `main` merge-base with `behind_by=0` immediately before PR creation.
- [ ] exact branch head passes Python 3.11 CI.
- [ ] exact branch head passes Python 3.12 CI.
- [ ] Ruff correctness checks pass.
- [ ] browser JavaScript syntax checks pass.
- [ ] complete pytest suite passes.
- [ ] package build produces `adaptive-agent-runtime==0.10.0`.
- [ ] README, `SECURITY.md`, Interactive Workspace, local-control security, and `LIVE_TURNS.md` agree on the security/correctness boundaries.
- [ ] PR is opened on a frozen exact head SHA.
- [ ] independent pull-request-triggered Python 3.11/3.12 matrix passes on that exact SHA.
- [ ] squash merge uses `expected_head_sha` to reject head movement.
- [ ] merged `main` commit passes Python 3.11/3.12 CI.
- [ ] GitHub Pages deploy succeeds for the merged commit.

## Explicit non-goals for 0.10

ARC 0.10 does not claim:

- vendor-native persistent/resumable sessions across all providers;
- browser stdin/PTY interaction with provider CLIs;
- durable reconstruction of browser-started provider process liveness after ARC restart;
- complete data-loss prevention for arbitrary sensitive repository output;
- provider filesystem/network sandboxing;
- authenticated remote/multi-user Workspace access;
- OpenRouter tool-using filesystem execution.

Those require separate designs and should not be implied by the live-turn UI.
