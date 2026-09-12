# ARC Interactive Workspace

ARC 0.7 exposes three layers above the same authoritative runtime:

```text
arc            → conversation-first terminal supervisor
arc ui         → session-centric browser workspace
arc supervise  → GitHub PR / CI / review supervisor
```

All three operate on the same task DAG, event log, provider profiles, ContextPackets, isolated Git worktrees, budgets, leases, and integration gate.

## Product model

ARC keeps **Task**, **WorkerSession**, and external **ReviewStatus** separate.

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

A worker session is the persistent supervised draft environment for one task:

```text
WorkerSession
├── task
├── agent/profile/model
├── immutable initial ContextPacket
├── isolated worktree + branch
├── conversation turns
├── changed files
├── current draft diff
├── terminal handoff state
└── submit/gate result
```

GitHub review state is an external projection:

```text
ReviewStatus
├── PR number + URL
├── check states
├── review decision
├── inline/general review feedback
├── snapshot digest
├── actionable-feedback digest
└── applied-feedback digest
```

The task remains authoritative. A conversation, pull request, green GitHub check, or approval does not make ARC work complete. Only a candidate that passes ARC's integration gate becomes integrated project state.

## Start the interactive CLI

After initializing the repository and signing into provider CLIs:

```bash
arc init .
arc login
arc
```

Plain text at project scope is treated as an objective:

```text
> add passwordless authentication, tests, and docs
```

ARC uses the current planner baseline to materialize tasks and reports likely routes. You can then run the fleet or take direct control of one worker.

Useful commands:

```text
/help
/status
/tasks
/sessions
/open T001
/focus S_12345678
/run
```

Once a worker is focused, ordinary text becomes the worker's next instruction:

```text
> keep the public API backward compatible and add tests for expired tokens
```

Inspect before integration:

```text
/files
/diff
```

## Closed-loop GitHub review

ARC delegates GitHub authentication to the existing `gh` CLI. It does not copy or persist GitHub tokens.

Check the integration first:

```bash
gh auth status
```

From the focused interactive worker:

```text
/publish
```

or script it directly:

```bash
arc session publish S_12345678
```

ARC commits the current draft if necessary, pushes the worker branch, and creates a pull request. Later calls push updates to the same PR.

Synchronize checks and reviews:

```text
/review
```

or:

```bash
arc session review S_12345678
```

When GitHub reports a failing check or requested review change, ARC records normalized external state in its own event stream. Actionable feedback is visible in the same worker session.

Apply the latest new feedback to the owning worker:

```text
/fix-review
```

or:

```bash
arc session review S_12345678 --apply
```

For ongoing synchronization:

```bash
arc supervise
```

To automatically route new actionable feedback into linked workers:

```bash
arc supervise --auto-apply
```

Run one synchronization pass for scripts/cron/systemd:

```bash
arc supervise --once
arc supervise --once --auto-apply
```

The supervisor only acts on PR-linked active worker sessions.

### Review events

GitHub remains non-authoritative. ARC records the external projection as events:

```text
session.pr_published
session.pr_updated
session.review_synced
session.review_feedback
session.review_feedback_applied
session.review_feedback_cleared
session.review_sync_failed
```

Snapshot state and actionable feedback use separate digests. This prevents the same reviewer instruction from being sent back to an agent merely because an unrelated check/merge state changed.

## Exact candidate after PR iteration

A PR-backed worker may accumulate several commits:

```text
worker branch
  A  initial implementation
  B  CI fix
  C  reviewer-requested fix
```

ARC's integration gate deliberately verifies exactly one immutable candidate. ARC therefore does **not** force-squash or rewrite the public review branch.

At submit time, when the worker branch contains multiple unique commits, ARC creates an unattached synthetic squash candidate:

```text
review branch A-B-C  ──tree──► synthetic candidate S
                                  parent = merge-base
                                  tree   = current worker HEAD
```

`S` represents the complete worker branch delta in one immutable commit. The gate cherry-picks and verifies `S`; the published PR history remains untouched.

A clean branch with no worker-authored commits still fails closed as a no-op.

## Scriptable worker lifecycle

The same operations are available without the interactive shell:

```bash
arc session open T001 --agent builder
arc session list
arc session show S_12345678
arc session send S_12345678 "add the edge-case tests"
arc session files S_12345678
arc session diff S_12345678
arc session publish S_12345678
arc session review S_12345678
arc session review S_12345678 --apply
arc session submit S_12345678
```

If ARC itself is restarted, the worker state is reconstructed from authoritative events and the draft worktree remains on disk:

```bash
arc session resume S_12345678
```

A stopped worker discards its draft workspace and returns an unfinished dispatched task to the READY frontier:

```bash
arc session stop S_12345678
```

## Native agent terminal

ARC can hand the worker's existing worktree to the provider's native terminal UI:

```bash
arc attach S_12345678
```

For example, a Codex-backed session opens Codex in that worker worktree. Claude, Antigravity and OpenCode use their corresponding native CLIs.

Important boundary:

- ARC does not copy provider credentials.
- ARC does not treat the provider process/PID as durable state.
- ARC records terminal attach lifecycle events and re-inspects the worktree when the provider exits.
- Draft changes remain unintegrated until `arc session submit`.

## Browser Workspace

Launch:

```bash
arc ui
```

Default:

```text
http://127.0.0.1:8788
```

The UI is inspired by modern local agent-supervision workspaces: a project orchestrator at the top, a live worker board in the center, and a detailed worker inspector on the right. ARC uses its own runtime semantics and visual language.

### Board columns

**Working**
- READY tasks that can be opened or orchestrated;
- open/running worker sessions.

**Needs you**
- failed/blocked tasks;
- failed/rejected/needs-input workers.

**In review**
- submitted session candidates moving through review/gate state.

**Resolved**
- accepted worker sessions and completed tasks.

### Worker inspector

For a persistent session the inspector exposes:

- **Chat** — send the next worker instruction;
- **Files** — uncommitted changed file surface;
- **Diff** — current uncommitted draft;
- **Review** — PR link, checks, requested changes, pending feedback, publish/sync/apply controls;
- **Context** — the immutable initial ContextPacket;
- **Events** — authoritative task/session/review trail;
- **Terminal** — trusted `arc attach SESSION` command.

Actions remain explicit:

```text
Open worker
Publish PR / Push update
Sync review
Apply feedback
Submit
Stop
```

The browser never interprets chat output or a green GitHub PR as a successful ARC patch. Submission still creates an immutable Git candidate and invokes the normal ARC gate.

## Persistence model

Session durability comes from two places:

```text
append-only ARC events  +  persistent isolated Git worktree
```

Review-loop continuity also comes from ARC events. `arc supervise` is a foreground supervisor process; if that process stops, the PR linkage and last normalized review state remain replayable and synchronization can resume later.

ARC deliberately does **not** claim that a vendor terminal process survives application restart. Process handles are ephemeral OS resources. After a restart, ARC reconstructs the worker and can launch another provider turn against the same draft worktree.

This makes recovery explicit instead of pretending that PIDs are durable project state.

## Session events

```text
session.created
session.message
session.turn_started
session.turn_finished
session.resumed
session.needs_input
session.terminal_started
session.terminal_stopped
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

The transcript and review projection are useful operational context, while task/gate/Git facts determine project correctness.

## Relationship to fleet orchestration

Interactive sessions and autonomous fleet execution coexist.

Opening a worker dispatches the task out of the READY frontier so `arc orchestrate` cannot race the interactive worker on the same task.

For autonomous execution:

```bash
arc orchestrate
```

For supervised execution:

```bash
arc session open T001
arc session send ...
arc session publish ...
arc session review ... --apply
arc session submit ...
```

Both routes converge on the same integration gate.

## Security

`arc ui` is localhost-only by default. It currently has no ARC-user authentication or RBAC.

Do not expose it to an untrusted network. `--allow-remote` only disables the loopback guard; it does not add authentication.

Provider-native authentication remains owned by each provider CLI. GitHub authentication remains owned by `gh`.

ARC does not put provider or GitHub credentials into `.arc/`, session events, or browser payloads.

## Current boundaries

Implemented through v0.7:

- persistent worker metadata and transcript;
- persistent worktree across ARC restart;
- repeated agent turns in the same worktree;
- native terminal handoff;
- files/diff/context/event inspection;
- explicit submit through ARC's transactional gate;
- interactive terminal shell;
- session-centric local browser workspace;
- GitHub PR publishing/updating through existing `gh` auth;
- normalized CI/review/inline-comment ingestion;
- actionable review feedback routed to the owning worker;
- foreground multi-worker review supervision;
- digest-based external-state and feedback deduplication;
- exact synthetic squash candidate for multi-commit reviewed branches.

Still open after v0.7:

- per-worker browser/application preview;
- stronger daemon/PTY supervision for long-lived provider processes;
- remote multi-user auth/RBAC;
- desktop packaging.
