# ARC Interactive Workspace

ARC 0.6 adds two product surfaces above the same authoritative runtime:

```text
arc       → conversation-first terminal supervisor
arc ui    → session-centric browser workspace
```

Both operate on the same task DAG, event log, provider profiles, ContextPackets, isolated Git worktrees, budgets, leases, and integration gate.

## Product model

ARC keeps **Task** and **WorkerSession** separate.

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

The task remains authoritative. A conversation does not make work complete. Only a candidate that passes ARC's integration gate becomes integrated project state.

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

Submit explicitly:

```text
/submit
```

## Scriptable worker lifecycle

The same operations are available without the interactive shell:

```bash
arc session open T001 --agent builder
arc session list
arc session show S_12345678
arc session send S_12345678 "add the edge-case tests"
arc session files S_12345678
arc session diff S_12345678
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
- **Files** — changed file surface;
- **Diff** — current unsubmitted draft;
- **Context** — the immutable initial ContextPacket;
- **Events** — authoritative task/session trail;
- **Terminal** — trusted `arc attach SESSION` command.

Actions are explicit:

```text
Open worker
Submit
Stop
```

The browser never interprets chat output as a successful patch. Submission still creates a Git candidate and invokes the normal ARC gate.

## Persistence model

Session durability comes from two places:

```text
append-only ARC events  +  persistent isolated Git worktree
```

ARC deliberately does **not** promise that a vendor terminal process survives application restart. Process handles are ephemeral OS resources. After a restart, ARC reconstructs the worker and can launch another provider turn against the same draft worktree.

This makes recovery explicit and replayable.

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
session.submitted
session.accepted
session.rejected
session.failed
session.stopped
```

The transcript is useful operational context, while task/gate/Git facts determine project correctness.

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
arc session submit ...
```

Both routes converge on the same integration gate.

## Security

`arc ui` is localhost-only by default. It currently has no ARC-user authentication or RBAC.

Do not expose it to an untrusted network. `--allow-remote` only disables the loopback guard; it does not add authentication.

Provider-native authentication remains owned by each provider CLI.

## Current boundaries

Implemented in v0.6:

- persistent worker metadata and transcript;
- persistent worktree across ARC restart;
- repeated agent turns in the same worktree;
- native terminal handoff;
- files/diff/context/event inspection;
- explicit submit through ARC's transactional gate;
- interactive terminal shell;
- session-centric local browser workspace.

Not yet implemented:

- durable PTY multiplexing across daemon restarts;
- per-worker browser preview;
- GitHub pull-request / CI / review ingestion;
- automatic review comments routed back to the owning worker;
- remote multi-user auth/RBAC;
- desktop packaging.
