# ARC Interactive Workspace

ARC 0.8 exposes four coordinated surfaces above the same authoritative runtime:

```text
arc            → conversation-first terminal supervisor
arc ui         → session-centric browser workspace
arc supervise  → GitHub PR / CI / review supervisor
arc terminal   → tmux-backed persistent provider PTY
```

All operate on the same task DAG, event log, provider profiles, ContextPackets, isolated Git worktrees, budgets, leases, and integration gate.

## Product model

ARC keeps authoritative work separate from operational projections.

```text
AUTHORITATIVE / CORRECTNESS                  OPERATIONAL / REBUILDABLE
Task DAG                                     WorkerSession conversation
ARC event log                                GitHub ReviewStatus projection
Git candidate                                tmux runtime liveness
IntegrationGate outcome                      preview readiness/output
Git repository state                         derived memory/context indexes
```

A green PR, live preview, running terminal, or successful agent turn does not complete a task. Integration still requires the normal ARC gate.

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

Explicit stop discards the draft worktree and returns unfinished dispatched work to the scheduler:

```bash
arc session stop S_12345678
```

## Provider terminal modes

ARC now offers two terminal modes.

### Synchronous native handoff

```bash
arc attach S_12345678
```

The provider owns the current terminal until it exits. ARC then re-inspects the draft workspace.

### Persistent PTY supervision

ARC 0.8 can delegate a provider PTY to tmux:

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
PID                   NOT authoritative
live PTY              owned by tmux
```

A newly launched ARC process can rediscover a still-running tmux session from its deterministic runtime identity plus ARC runtime events. ARC never claims that a raw PID is durable state.

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

Default control-plane origin:

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

- **Chat** — continue the worker conversation;
- **Files** — uncommitted changed files;
- **Diff** — current draft diff;
- **Preview** — launch/stop a loopback dev server, inspect output, embed/open the app;
- **Review** — PR, CI, requested changes, pending feedback, publish/sync/apply;
- **Context** — immutable initial ContextPacket;
- **Events** — authoritative task/session/review/runtime trail;
- **Terminal** — start/stop persistent tmux PTY, inspect output, copy attach command.

The preview is loaded directly from its own localhost port rather than proxied through ARC:

```text
ARC Workspace   http://127.0.0.1:8788
worker preview  http://127.0.0.1:3000
```

Different ports mean different browser origins. Untrusted application content does not become part of ARC's control-plane origin.

## Runtime lifecycle invariant

ARC must not intentionally remove a worker worktree while an ARC-managed terminal or preview still owns it.

Submit/stop therefore follows:

```text
stop preview
    ↓
stop persistent terminal
    ↓
submit/gate OR stop worker
    ↓
remove worktree when lifecycle permits
```

Runtime start/stop API operations also use the Workspace's per-worker action lock to avoid racing another supervised action on the same worker.

## Persistence model

ARC 0.8 distinguishes several forms of persistence:

```text
append-only ARC events       authoritative/replayable
isolated Git worktree        persistent draft
GitHub PR linkage            replayable external projection
review digests               replayable external projection
tmux runtime                 live operational state
runtime metadata events      replayable operational history
```

If ARC exits while tmux remains alive, a new ARC process can rediscover the live runtime. If tmux itself disappears, project truth is unaffected; ARC reports the historical runtime as no longer live.

## Session/runtime events

Worker lifecycle events include:

```text
session.created
session.message
session.turn_started
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

Transcripts, review state, previews, PTYs and runtime output are operational context. Task/Git/gate facts determine project correctness.

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
arc session send ...
arc session preview-start ...
arc session publish ...
arc session review ... --apply
arc session submit ...
```

Both converge on the same integration gate.

## Security

`arc ui` remains localhost-only by default and does not yet provide ARC-user authentication/RBAC.

Provider authentication stays owned by the provider CLI. GitHub authentication stays owned by `gh`. ARC does not copy those credentials into `.arc/` or browser payloads.

Runtime event persistence redacts obvious secret-valued command arguments. Preview binding is loopback-only. The preview is not reverse-proxied through the ARC control-plane origin.

## Current boundaries

Implemented through v0.8:

- persistent worker metadata/transcript/worktree;
- multi-turn worker conversations;
- worker recovery after ARC restart;
- files/diff/context/event inspection;
- synchronous provider terminal handoff;
- tmux-backed persistent provider PTY;
- runtime rediscovery after ARC application restart;
- per-worker loopback application preview;
- preview/terminal log-tail inspection;
- runtime cleanup before worktree deletion;
- interactive terminal supervisor;
- session-centric browser Workspace;
- GitHub PR publishing/updating through existing `gh` auth;
- normalized CI/review/inline-comment ingestion;
- actionable feedback routed to the owning worker;
- foreground review supervision;
- exact synthetic candidate for multi-commit reviewed branches;
- explicit transactional integration gate.

Remaining product/research work is now outside the original v0.6 product gaps:

- authenticated remote/multi-user Workspace mode;
- desktop packaging;
- stronger provider credential/container isolation;
- learned planner/router policies;
- repository-scale iso-cost evaluation;
- semantic embedding provider / richer adaptive memory experiments.
