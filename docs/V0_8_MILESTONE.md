# ARC 0.8 Milestone — Persistent Worker Runtime Supervision

ARC 0.8 closes the two runtime/product gaps intentionally left after v0.7:

1. persistent provider PTY supervision;
2. per-worker browser/application preview.

## Delivered

### tmux-backed persistent provider PTY

```text
WorkerSession
    │
    ▼
ARC runtime metadata/events
    │
    ▼
tmux named session
    │
    ▼
Codex / Claude / Antigravity / OpenCode terminal
```

ARC never persists a raw PID as project truth. A new ARC application instance can rediscover a still-running terminal through deterministic runtime identity plus replayed runtime events.

### Isolated worker application preview

```text
worker Git worktree
       │
       ▼
loopback dev server
       │
       ├── output tail
       ├── readiness
       └── separate-origin browser preview
```

Preview commands must expose `{host}` and `{port}` so ARC controls the endpoint. Only loopback bindings are accepted.

### Workspace integration

`arc ui` now exposes:

- Preview tab;
- command template + port;
- STARTING / READY / STOPPED projection;
- direct preview URL;
- embedded preview iframe;
- runtime log tail;
- persistent Terminal state;
- terminal runtime name/output;
- terminal Start / Stop controls;
- `arc terminal SESSION` attach command.

### Runtime lifecycle invariant

ARC stops managed preview/terminal runtimes before a submitted/stopped worker worktree can be removed.

```text
stop preview
stop terminal
      │
      ▼
 submit/gate or stop
      │
      ▼
worktree cleanup
```

Runtime status remains replayable after worktree cleanup.

### Concurrency + security

- Workspace runtime mutations use the per-worker action lock.
- previews are loopback-only;
- preview application content remains on its own browser origin;
- obvious secret-valued command arguments are redacted from runtime events;
- tmux is optional local infrastructure, not an execution sandbox;
- provider/GitHub credentials remain provider-owned.

## Commands

```bash
arc terminal SESSION
arc terminal SESSION --start-only
arc session terminal-status SESSION
arc session terminal-stop SESSION

arc session preview-start SESSION \
  --command "npm run dev -- --host {host} --port {port}" \
  --port 3000
arc session preview-status SESSION
arc session preview-stop SESSION
```

## Verification

CI uses a deterministic fake-tmux backend and validates:

- runtime start/status/stop;
- runtime rediscovery after reconstructing ARC application state;
- event persistence;
- loopback preview enforcement;
- Workspace runtime API;
- Preview/Terminal browser assets;
- runtime cleanup before worktree deletion;
- runtime status after accepted worktree cleanup;
- JavaScript syntax;
- the full existing ARC regression suite;
- package build on Python 3.11 and 3.12.

## Correctness boundary

ARC 0.8 does not change what makes project work complete:

```text
live terminal       ─┐
live preview         │
green external PR    ├── not authoritative completion
agent chat result    │
derived memory       ─┘

Task → exact Git candidate → IntegrationGate → gate.accepted
```

With v0.8, the original interactive-supervision gaps are closed. Remaining work moves to security hardening, packaging, research policies, and repository-scale evaluation rather than missing core operator workflow.
