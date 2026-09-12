# ARC Interactive Workspace

ARC 0.10 exposes coordinated supervision surfaces above the same authoritative runtime:

```text
arc            → conversation-first terminal supervisor
arc ui         → session-centric browser Workspace + supervised live turns
arc supervise  → GitHub PR / CI / review supervisor
arc terminal   → tmux-backed persistent provider PTY
```

All operate on the same task DAG, event log, provider profiles, ContextPackets, isolated Git worktrees, budgets, leases, and integration gate.

## Product model

ARC keeps authoritative work separate from operational projections.

```text
AUTHORITATIVE / CORRECTNESS                  OPERATIONAL / REBUILDABLE
Task DAG                                     WorkerSession conversation
ARC event log                                provider turn output/process liveness
Git candidate                                GitHub ReviewStatus projection
IntegrationGate outcome                      tmux runtime liveness
Git repository state                         preview readiness/output
                                             derived memory/context indexes
```

A provider printing “done”, a cancelled turn, green PR, live preview, running terminal, or successful agent turn does not complete a task. Integration still requires the normal ARC gate.

## Task and WorkerSession

A task is authoritative work:

```text
Task
├── goal
├── dependencies
├── declared files
├── acceptance criteria
├── risk
└── lifecycle state
```

A worker session is the supervised draft environment for one task:

```text
WorkerSession
├── task
├── agent/profile/model
├── immutable initial ContextPacket
├── isolated worktree + branch
├── conversation turns
├── supervised TURN_* lifecycle/output
├── changed files + draft diff
├── optional GitHub review projection
├── optional live terminal / preview runtimes
└── submit/gate result
```

## Start the interactive CLI

```bash
arc init .
arc login
arc
```

At project scope, plain text becomes an objective:

```text
> add passwordless authentication, tests, and docs
```

ARC materializes tasks and reports routes. You can execute the READY fleet or open a persistent worker directly.

Useful controls:

```text
/help
/status
/tasks
/sessions
/open T001
/focus S_12345678
/run
```

With a focused worker, ordinary text becomes the next instruction:

```text
> keep the public API backward compatible and add tests for expired tokens
```

Inspect its draft:

```text
/files
/diff
```

The terminal `arc session send` path remains blocking/scriptable. For live provider output and explicit cancellation, use the browser Workspace described below.

## Supervised live turns

ARC 0.10 adds an asynchronous browser turn mode. Sending an instruction in the Workspace Chat starts a provider turn and returns control immediately rather than waiting for the provider CLI to exit.

```text
operator instruction
        ↓
TURN_0123456789
        ↓
provider subprocess ───► redacted stdout/stderr
        │                        │
        │                        ▼
        │               session.turn_output
        │                        │
        │                        ▼
        │                 /ws/events
        │
        └──── cancellation ◄──── operator
```

Every turn gets a stable `TURN_*` identifier that is attached to its instruction, lifecycle events, output events, assistant summary, and failure/cancellation outcome.

The browser uses three provider-neutral APIs:

```text
POST /api/sessions/{session_id}/turn
GET  /api/sessions/{session_id}/turn
POST /api/sessions/{session_id}/turn/cancel
```

Starting a turn returns `202` with operational state. Output then arrives through ARC's existing event WebSocket; the browser does not depend on provider-specific streaming APIs.

### Turn events

```text
session.turn_started
session.turn_output
session.turn_cancel_requested
session.turn_cancelled
session.turn_finished
session.failed
```

`session.turn_output` is durable/replayable operational history, but provider process liveness is not inferred from it. Output is redacted before it is persisted or emitted to the browser.

### Cancellation

Cancellation never becomes successful completion:

```text
Cancel turn
   ↓
session.turn_cancel_requested
   ↓
terminate provider
   ↓
kill escalation if required
   ↓
session.turn_cancelled
   ↓
WorkerSession returns OPEN
```

Draft edits already written before cancellation remain in the isolated worktree. The operator can inspect them, continue with another turn, discard the worker, or submit later through the normal gate.

### Per-worker locking

A live turn acquires the same per-worker action lock used by Workspace review/runtime actions before the start API returns. Submit, review publication/synchronization/application, and conflicting runtime mutations therefore cannot race a provider editing the same worktree. Cancellation is allowed to cross that lock so it can stop the process that owns it.

See [LIVE_TURNS.md](LIVE_TURNS.md) for the complete lifecycle, redaction, cleanup, and restart contract.

## Closed-loop GitHub review

ARC delegates GitHub authentication to the existing `gh` CLI. It does not copy or persist GitHub tokens.

Publish the focused worker:

```text
/publish
```

or:

```bash
arc session publish S_12345678
```

Synchronize GitHub checks/reviews:

```text
/review
```

or:

```bash
arc session review S_12345678
```

Apply the latest new actionable feedback to the same worker:

```text
/fix-review
```

or:

```bash
arc session review S_12345678 --apply
```

Supervise all linked workers:

```bash
arc supervise
arc supervise --auto-apply
arc supervise --once --auto-apply
```

GitHub remains a non-authoritative review surface. ARC records normalized review state as replayable events and uses separate snapshot/feedback digests so unrelated check-state churn cannot resend identical reviewer instructions.

### Review events

```text
session.pr_published
session.pr_updated
session.review_synced
session.review_feedback
session.review_feedback_applied
session.review_feedback_cleared
session.review_sync_failed
```

## Exact candidate after PR iteration

A reviewed worker may accumulate several public commits:

```text
A initial implementation
B CI fix
C requested-change fix
```

ARC does not rewrite that public review history. At submit time, a multi-commit worker branch is represented by an unattached synthetic candidate whose tree equals current worker HEAD and whose parent is the worker/integration merge-base.

```text
review branch A-B-C  ──tree──► synthetic candidate S
                                  parent = merge-base
                                  tree   = current worker HEAD
```

The IntegrationGate validates and integrates `S`, preserving the one-candidate correctness boundary. A true no-op still fails closed.

## Scriptable worker lifecycle

```bash
arc session open T001 --agent builder
arc session list
arc session show S_12345678
arc session send S_12345678 "add the edge-case tests"
arc session files S_12345678
arc session diff S_12345678
arc session publish S_12345678
arc session review S_12345678 --apply
arc session submit S_12345678
```

If ARC itself restarts, the worker is reconstructed from events while its isolated worktree remains on disk:

```bash
arc session resume S_12345678
```

A browser-started provider subprocess itself is not durable. If an ARC restart leaves a historical `session.turn_started` without a terminal turn event, ARC does not automatically launch a duplicate provider. Resume/recovery is explicit against the surviving worktree.

Explicit stop discards the draft worktree and returns unfinished dispatched work to the scheduler:

```bash
arc session stop S_12345678
```

If the Workspace owns an active live turn, browser Stop first cancels and waits for that provider process before removing the worktree.

## Provider terminal modes

ARC offers a synchronous native handoff and a persistent tmux-backed PTY in addition to browser supervised turns.

### Synchronous native handoff

```bash
arc attach S_12345678
```

The provider owns the current terminal until it exits. ARC then re-inspects the draft workspace.

### Persistent PTY supervision

ARC can delegate a provider PTY to tmux:

```bash
arc terminal S_12345678
```

Start without attaching:

```bash
arc terminal S_12345678 --start-only
```

Inspect or stop:

```bash
arc session terminal-status S_12345678
arc session terminal-stop S_12345678
```

The distinction is important:

```text
ARC event log        durable/replayable metadata
WorkerSession        durable/replayable worker identity
Git worktree         durable draft workspace
browser turn process disposable operational state
tmux PTY             live operational state owned by tmux
PID                  NOT authoritative
```

A newly launched ARC process can rediscover a still-running tmux session from its deterministic runtime identity plus ARC runtime events. ARC does not make the same claim for browser live-turn subprocesses.

See [PERSISTENT_RUNTIMES.md](PERSISTENT_RUNTIMES.md).

## Worker application preview

A worker can run a localhost dev server inside its isolated worktree:

```bash
arc session preview-start S_12345678 \
  --command "npm run dev -- --host {host} --port {port}" \
  --port 3000
```

or:

```bash
arc session preview-start S_12345678 \
  --command "python -m http.server {port} --bind {host}" \
  --port 3000
```

Inspect/stop:

```bash
arc session preview-status S_12345678
arc session preview-stop S_12345678
```

ARC requires `{host}` and `{port}` placeholders so it controls the bind endpoint. Preview hosts are restricted to loopback (`127.0.0.1`, `localhost`, or `::1`). Public binds such as `0.0.0.0` are rejected.

## Browser Workspace

Launch:

```bash
arc ui
```

The control-plane origin is strictly local-only:

```text
http://127.0.0.1:8788
```

The Workspace has a project orchestrator, worker board, and detailed worker inspector.

### Board columns

**Working**
- READY tasks;
- active worker sessions.

**Needs you**
- failed/blocked tasks;
- failed/rejected/needs-input workers.

**In review**
- submitted/reviewing session candidates.

**Resolved**
- accepted workers and completed tasks.

### Worker inspector

A persistent worker exposes:

- **Chat** — start a supervised `TURN_*`, stream redacted provider stdout/stderr, cancel the active turn, and continue the conversation;
- **Files** — uncommitted changed files;
- **Diff** — current draft diff;
- **Preview** — launch/stop a loopback dev server, inspect output, embed/open the app;
- **Review** — PR, CI, requested changes, pending feedback, publish/sync/apply;
- **Context** — immutable initial ContextPacket;
- **Events** — authoritative task/session/review/runtime trail plus replayable turn output;
- **Terminal** — start/stop persistent tmux PTY, inspect output, copy attach command.

The preview is loaded directly from its own localhost port rather than proxied through ARC:

```text
ARC Workspace   http://127.0.0.1:8788
worker preview  http://127.0.0.1:3000
```

Different ports mean different browser origins. Untrusted application content does not become part of ARC's control-plane origin.

## Runtime lifecycle invariant

ARC must not intentionally remove a worker worktree while an ARC-managed live process still owns it.

A Workspace stop follows:

```text
cancel supervised live turn
    ↓
wait for provider process exit
    ↓
stop preview / persistent terminal when applicable
    ↓
stop worker or submit/gate
    ↓
remove worktree when lifecycle permits
```

Runtime/review/submit API operations use the Workspace per-worker action lock to avoid racing another supervised action on the same worker.

## Persistence model

ARC distinguishes several forms of persistence:

```text
append-only ARC events       authoritative/replayable project + operational history
isolated Git worktree        persistent draft
GitHub PR linkage            replayable external projection
review digests               replayable external projection
session.turn_output          replayable redacted provider observation
tmux runtime                 live operational state that may survive ARC restart
browser turn subprocess      disposable operational state
runtime metadata events      replayable operational history
```

If ARC exits while tmux remains alive, a new ARC process can rediscover the live runtime. If a browser turn process disappears with ARC, project truth is unaffected; the surviving worktree/event history remains available for explicit recovery.

## Session/runtime events

Worker lifecycle events include:

```text
session.created
session.message
session.turn_started
session.turn_output
session.turn_cancel_requested
session.turn_cancelled
session.turn_finished
session.resumed
session.needs_input
session.terminal_started
session.terminal_stopped
session.runtime_started
session.runtime_stopped
session.terminal_attached
session.pr_published
session.pr_updated
session.review_synced
session.review_feedback
session.review_feedback_applied
session.submitted
session.accepted
session.rejected
session.failed
session.stopped
```

Transcripts, redacted provider output, review state, previews, PTYs and runtime output are operational context. Task/Git/gate facts determine project correctness.

## Relationship to autonomous orchestration

Interactive sessions and fleet execution coexist.

Opening a worker dispatches its task out of the READY frontier, preventing `arc orchestrate` from racing the interactive worker.

Autonomous execution:

```bash
arc orchestrate
```

Supervised execution:

```bash
arc session open T001
# Continue in `arc ui` for streamed/cancellable browser turns, or:
arc session send ...
arc session preview-start ...
arc session publish ...
arc session review ... --apply
arc session submit ...
```

Both converge on the same integration gate.

## Security

`arc ui` and `arc web` are strictly loopback-only unauthenticated developer control planes. The legacy `--allow-remote` option does not bypass that restriction. Browser HTTP and WebSocket Origins are validated against explicit localhost/literal-loopback hosts.

Provider authentication stays owned by the provider CLI. GitHub authentication stays owned by `gh`. ARC does not copy those credentials into `.arc/` or browser configuration payloads.

Provider subprocesses receive provider-scoped least-privilege environments. In live-turn mode, credential-like environment values and common provider token forms are redacted from stdout/stderr before the text enters ARC events, WebSocket payloads, or final provider summaries. This is defense in depth rather than complete DLP or process sandboxing.

Preview binding is loopback-only. Preview content is not reverse-proxied through the ARC control-plane origin.

See [../SECURITY.md](../SECURITY.md), [EXECUTION_SECURITY.md](EXECUTION_SECURITY.md), [LOCAL_CONTROL_PLANE_SECURITY.md](LOCAL_CONTROL_PLANE_SECURITY.md), and [LIVE_TURNS.md](LIVE_TURNS.md).

## Current boundaries

Implemented through v0.10:

- persistent worker metadata/transcript/worktree;
- multi-turn worker conversations;
- supervised asynchronous browser provider turns;
- incremental redacted stdout/stderr turn events;
- explicit provider-turn cancellation and process cleanup;
- worker stop waits for supervised turn exit before worktree removal;
- worker recovery after ARC restart without automatically duplicating provider execution;
- files/diff/context/event inspection;
- synchronous provider terminal handoff;
- tmux-backed persistent provider PTY;
- runtime rediscovery after ARC application restart;
- per-worker loopback application preview;
- preview/terminal log-tail inspection;
- runtime cleanup before worktree deletion;
- least-privilege provider environments;
- strict local-only browser control planes + Origin protection;
- interactive terminal supervisor;
- session-centric browser Workspace;
- GitHub PR publishing/updating through existing `gh` auth;
- normalized CI/review/inline-comment ingestion;
- actionable feedback routed to the owning worker;
- foreground review supervision;
- exact synthetic candidate for multi-commit reviewed branches;
- explicit transactional integration gate.

Remaining product/research work includes:

- authenticated remote/multi-user Workspace mode;
- full provider filesystem/network sandboxing;
- richer CLI-native streaming/cancellation controls;
- desktop packaging;
- learned planner/router policies;
- repository-scale iso-cost evaluation;
- semantic embedding provider / richer adaptive memory experiments.
