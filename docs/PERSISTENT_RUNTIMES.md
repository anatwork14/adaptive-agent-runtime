# ARC Persistent Worker Runtimes

ARC 0.8 adds an optional live-runtime layer for provider terminals and application previews.

The design rule is deliberately strict:

> **A live process is operational state, not authoritative project state.**

ARC does not persist a PID and pretend that a process is durable. Instead:

```text
ARC event log + WorkerSession metadata
                │
                ▼
      tmux runtime identity
                │
        ┌───────┴────────┐
        ▼                ▼
 provider terminal   preview server
```

`tmux` owns the live PTY/process. ARC owns replayable metadata describing why it was started, its worker/session association, the workspace, sanitized command metadata, and start/stop lifecycle events.

## Why tmux

ARC needs a live terminal or dev server to survive the command that launched it and, when possible, survive an ARC CLI restart. Building a custom terminal multiplexer would add a large process-control surface unrelated to ARC's research/correctness contribution.

`tmux` gives ARC:

- detached long-lived processes;
- PTY ownership for interactive provider CLIs;
- explicit attach/detach;
- named runtime discovery;
- output capture;
- idempotent stop semantics;
- a mature local operational boundary.

ARC still treats the tmux server as disposable infrastructure. If tmux disappears, project truth remains reconstructable from ARC events and Git state.

## Install tmux

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y tmux
```

macOS:

```bash
brew install tmux
```

Check through ARC:

```bash
arc session terminal-status SESSION
```

The Workspace also exposes the runtime doctor endpoint at `/api/runtime/doctor`.

## Persistent provider terminal

The existing synchronous provider handoff remains available:

```bash
arc attach SESSION
```

ARC 0.8 adds persistent PTY mode:

```bash
arc terminal SESSION
```

This starts or reuses a tmux-backed terminal for the worker and attaches the current terminal to it.

Start it without attaching:

```bash
arc terminal SESSION --start-only
```

Inspect:

```bash
arc session terminal-status SESSION
```

Stop:

```bash
arc session terminal-stop SESSION
```

The runtime name is deterministic from the ARC session ID, so a newly created `SessionArcApplication` can rediscover a still-running tmux session after the ARC command that launched it has exited.

## Worker application preview

A worker can run a dev server directly inside its isolated Git worktree.

ARC requires the command template to expose both `{host}` and `{port}` placeholders:

```bash
arc session preview-start SESSION \
  --command "npm run dev -- --host {host} --port {port}" \
  --port 3000
```

Python static preview example:

```bash
arc session preview-start SESSION \
  --command "python -m http.server {port} --bind {host}" \
  --port 3000
```

Inspect:

```bash
arc session preview-status SESSION
```

Stop:

```bash
arc session preview-stop SESSION
```

## Preview security boundary

ARC previews are **loopback-only**.

Allowed hosts:

```text
127.0.0.1
localhost
::1
```

ARC rejects `0.0.0.0`, public interfaces, and preview commands that do not expose `{host}` and `{port}`. This prevents a convenience preview command from silently turning ARC into a network-exposure mechanism.

The browser Workspace loads the preview from the preview server's own localhost port. ARC does not proxy arbitrary application content through the privileged Workspace origin.

This means:

```text
ARC control plane     http://127.0.0.1:8788
worker preview        http://127.0.0.1:3000
```

They are separate browser origins because the ports differ.

## Workspace Preview tab

Run:

```bash
arc ui
```

Select a worker and open **Preview**.

The inspector exposes:

- command template;
- port;
- STARTING / READY / STOPPED state;
- direct preview URL;
- runtime output tail;
- embedded application preview;
- open-in-new-tab action;
- explicit stop.

The **Terminal** tab similarly exposes:

- persistent tmux runtime state;
- runtime name;
- `arc terminal SESSION` attach command;
- terminal output tail;
- Start / Stop controls.

## Runtime events

ARC records:

```text
session.runtime_started
session.runtime_stopped
session.terminal_attached
```

A runtime-start event includes:

```text
session_id
runtime_kind     terminal | preview
backend          tmux
runtime_name
sanitized command argv
workspace
host / port / URL for preview
```

Obvious secret-valued command arguments are redacted before event persistence. Provider credentials themselves remain owned by provider-native credential stores.

## Restart model

Consider:

```text
1. ARC starts preview P for WorkerSession S.
2. ARC CLI exits.
3. tmux continues owning P.
4. ARC starts again.
5. ARC replays session.runtime_started for S.
6. ARC asks tmux whether the deterministic runtime name still exists.
7. UI/CLI reports the live runtime again.
```

No PID is persisted as project truth.

If the tmux runtime has disappeared, ARC reports it as non-running even though the historical start event remains in the event log.

## Worktree lifetime invariant

ARC never intentionally deletes a worker worktree while an ARC-managed live runtime still owns that workspace.

For both explicit stop and integration submission:

```text
stop preview
    ↓
stop terminal
    ↓
freeze / gate or stop worker
    ↓
remove worktree when lifecycle permits
```

This prevents an orphaned provider process or dev server from continuing against a deleted/stale working directory.

If ARC cannot safely determine/terminate a previously started runtime, cleanup fails rather than silently treating the live process as irrelevant.

## Concurrency

Workspace runtime mutations share the same per-worker action lock used by other supervised actions. A runtime start/stop therefore cannot race another Workspace action for the same worker.

Read-only status remains available independently.

## What remains non-authoritative

None of these establish project correctness:

- a running terminal;
- a running preview;
- preview readiness;
- terminal output;
- process lifetime;
- tmux session existence.

Correctness still flows through:

```text
Task DAG
  ↓
immutable/context-versioned worker execution
  ↓
Git candidate
  ↓
IntegrationGate
  ↓
gate.accepted
  ↓
authoritative Git + ARC event state
```

## Failure behavior

- tmux missing → persistent runtime commands report setup required;
- requested preview port occupied → preview start fails;
- public/non-loopback host → rejected;
- command lacks ARC-controlled host/port placeholders → rejected;
- duplicate running preview → rejected until explicitly stopped;
- runtime process exits → next status projection reports non-running;
- ARC restarts → event metadata + tmux identity reconstruct runtime status;
- worker submit/stop → ARC terminates managed runtimes before worktree cleanup.

## Testing

CI does not depend on tmux being installed. A deterministic fake tmux backend verifies:

- start/status/stop behavior;
- event persistence;
- runtime rediscovery after recreating ARC application state;
- preview loopback enforcement;
- Workspace API routes;
- browser runtime assets;
- submit cleanup ordering before worktree deletion.

The production `TmuxController` remains a small adapter around the real `tmux` executable.
