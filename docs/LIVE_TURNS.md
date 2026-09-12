# ARC Supervised Live Turns

ARC 0.10 makes interactive provider turns observable and cancellable without changing ARC's correctness boundary.

The key rule remains:

> **A live provider process is operational state, not authoritative project state.**

Worker continuity still comes from the append-only ARC event log plus the isolated Git worktree. A provider process may disappear, be cancelled, or be relaunched without becoming the source of truth for what the project contains.

## Why this exists

Before 0.10, a persistent `WorkerSession` survived ARC restarts, but each real provider turn behaved like a blocking subprocess call:

```text
operator instruction
       ↓
provider CLI
       ↓
wait for process exit
       ↓
collect all stdout/stderr
       ↓
return one response
```

That meant the Workspace could not show meaningful progress while Codex, Claude, Antigravity, or OpenCode was working, and it could not explicitly cancel the live provider turn.

ARC 0.10 changes the operational path to:

```text
operator instruction
       ↓
TURN_<id>
       ↓
provider subprocess ──────► redacted output lines
       │                          │
       │                          ▼
       │                 session.turn_output
       │                          │
       │                          ▼
       │                  Workspace WebSocket
       │
       ├──────── cancel request ◄──── operator
       │
       ▼
finished / cancelled / failed
       ↓
inspect draft worktree
       ↓
explicit submit
       ↓
exact Git candidate
       ↓
IntegrationGate
```

## Turn identity

Every worker turn receives a stable identifier:

```text
TURN_0123456789
```

The identifier is included on the user instruction, turn lifecycle events, streamed output, assistant summary, and failures. This allows the UI and later evaluation tooling to attribute output to the exact provider attempt rather than only to the broader worker session.

## Event model

ARC 0.10 adds/uses the following turn events:

```text
session.turn_started
session.turn_output
session.turn_cancel_requested
session.turn_cancelled
session.turn_finished
session.failed
```

`session.turn_output` payloads contain:

```json
{
  "session_id": "S_12345678",
  "turn_id": "TURN_0123456789",
  "sequence": 1,
  "stream": "stdout",
  "content": "redacted provider output\n"
}
```

The event log records the observable turn history. It does **not** make the provider process itself durable.

## Streaming behavior

Real subprocess-backed adapters read stdout and stderr incrementally. ARC emits redacted text to the event stream as provider lines arrive instead of waiting for process exit.

Workspace uses the existing `/ws/events` channel. It does not open a provider-specific stream and does not require provider-specific browser code.

`session.turn_output` is treated specially in the browser: output is appended directly to the live inspector rather than forcing a full project snapshot reload for every line. Lifecycle events still refresh the authoritative projections.

## Secret redaction before persistence

Provider output is potentially sensitive. A coding CLI can echo environment values, command output, authentication diagnostics, or tokens.

ARC therefore applies output redaction **before** streamed provider text reaches:

- `session.turn_output` events;
- Workspace WebSocket payloads;
- final provider summaries;
- failure summaries containing stderr tails.

The redactor masks:

- values of credential-like environment variables forwarded to the provider;
- common provider-token forms such as `sk-*`, `sess-*`, Google `ya29.*`, and bearer tokens.

Provider output is line-buffered before redaction so a credential split across lower-level OS read chunks is not persisted as separate unredacted fragments.

This is defense in depth, not a complete data-loss-prevention system. Agents can still read files or network resources available to their host-mode process unless stronger sandboxing is configured.

## Workspace API

The original blocking API remains available for compatibility:

```text
POST /api/sessions/{session_id}/messages
```

ARC 0.10 adds asynchronous supervised-turn endpoints:

```text
POST /api/sessions/{session_id}/turn
GET  /api/sessions/{session_id}/turn
POST /api/sessions/{session_id}/turn/cancel
```

Starting a live turn returns `202` immediately with operational state such as:

```json
{
  "session_id": "S_12345678",
  "turn_id": "TURN_0123456789",
  "active": true,
  "done": false,
  "cancel_requested": false,
  "error": null
}
```

Provider output then arrives through the normal ARC event WebSocket.

## Worker locking

A live turn acquires the same per-worker action lock already used by Workspace review/runtime actions **before the start endpoint returns**.

While that provider is editing its worktree, ARC rejects conflicting actions such as:

- submit;
- review feedback application;
- review publication/synchronization;
- runtime mutations that use the same worker lock.

This avoids a window where the UI reports a turn as started but another request races into the same worktree.

## Cancellation

Cancellation is explicit and observable:

```text
operator clicks Cancel
       ↓
session.turn_cancel_requested
       ↓
async cancellation signal
       ↓
provider receives terminate
       ↓
kill escalation if necessary
       ↓
session.turn_cancelled
       ↓
worker returns to OPEN
```

Cancellation is **not** recorded as a successful provider result and does not complete the task.

Draft changes already written before cancellation remain in the isolated worktree for inspection. The operator can continue the worker, discard it, or submit it later through the normal gate.

## Safe worker stop

Stopping a worker while a browser-started live turn is active follows:

```text
request turn cancellation
       ↓
wait for provider process exit
       ↓
release worker action lock
       ↓
stop WorkerSession
       ↓
remove worktree
```

ARC will not intentionally delete the worktree underneath a provider process it is supervising.

## Server shutdown

Workspace shutdown requests cancellation for active supervised turns and waits for process cleanup. `SubprocessCodingAgent` also handles asyncio task cancellation by terminating its child process, providing a final cleanup path if the supervisor task itself is cancelled.

## Restart semantics

The event log and worktree survive an ARC restart. The provider process used by the asynchronous Workspace turn does not.

If ARC restarts after recording `session.turn_started` but before a terminal lifecycle event, the projected worker may still appear `RUNNING`. ARC intentionally does **not** guess that the old provider is alive and does not launch a duplicate provider turn automatically.

The recovery path is explicit:

```text
inspect surviving worktree
       ↓
resume WorkerSession
       ↓
continue with a new turn
```

This preserves the rule that process liveness is not reconstructed from stale metadata.

## Relationship to persistent tmux terminals

ARC still supports `arc terminal SESSION`, where tmux owns a provider PTY that can survive the invoking ARC process.

That is a different interaction mode:

```text
Workspace live turn    ARC owns one cancellable subprocess turn
Persistent terminal    tmux owns an interactive provider PTY
```

Neither process is authoritative project state. Both edit the isolated worker worktree, and completion still requires the exact-candidate IntegrationGate.

## Correctness boundary

Streaming changes observability, not acceptance:

```text
provider output / chat / memory / GitHub review / preview
                         ↓
                  operational context
                         ↓
                 isolated worktree
                         ↓
                 exact Git candidate
                         ↓
                  IntegrationGate
                         ↓
                authoritative state
```

A provider printing “done” is not task completion. A cancelled turn is not task completion. A green external PR is not task completion. ARC completes work only when the exact candidate passes its integration boundary.
