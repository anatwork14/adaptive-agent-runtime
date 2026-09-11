# ARC Web Mission Control

ARC v0.3 adds a localhost browser control plane over the same `ArcApplication` used by the Typer CLI and Textual TUI.

## Launch

From an initialized ARC repository:

```bash
arc web --open
```

Default address:

```text
http://127.0.0.1:8787
```

Change the port when needed:

```bash
arc web --port 9000
```

## Security default

The browser UI currently has **no authentication layer**, so ARC binds to loopback by default.

This is allowed:

```bash
arc web --host 127.0.0.1
```

This is rejected by default:

```bash
arc web --host 0.0.0.0
```

Remote binding requires an explicit acknowledgement:

```bash
arc web --host 0.0.0.0 --allow-remote
```

Only use `--allow-remote` behind a trusted network boundary or a separate authenticated reverse proxy. The flag changes the bind safety check; it does not add authentication.

## What the browser shows

The Web Mission Control dashboard exposes:

```text
project / state version / budget / memory / leases
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
       Task DAG        Agents       Mission detail
          │              │              │
          └──────────────┼──────────────┘
                         ▼
             Authoritative event stream
```

Operators can create tasks, select tasks, run READY tasks, retry failed/blocked tasks, cancel unfinished tasks, inspect a compiled ContextPacket summary, add named agent profiles, and see provider doctor state.

## Shared runtime boundary

The browser is not a separate ARC implementation.

```text
Browser JavaScript
       │ HTTP / WebSocket
       ▼
FastAPI Mission Control
       │
       ▼
ArcApplication
       │
       ▼
Orchestrator
```

All project/task/memory state still comes from the same event store, deterministic projections, and Git integration layer used by `arc`, `arc watch`, and `arc dashboard`.

Web-triggered task execution is serialized by one application-level execution lock so two browser clicks cannot intentionally launch competing integration writers from the same server instance.

## Live events

The browser connects to:

```text
/ws/events
```

The WebSocket polls ARC's append-only event store through the same `EventStream` abstraction used by other UI surfaces. It streams authoritative events; it does not create a second telemetry database.

The event cursor can resume from a known event ID:

```text
/ws/events?after=4812
```

## HTTP API

The current local API includes:

```text
GET  /api/health
GET  /api/snapshot
GET  /api/events
GET  /api/tasks/{task_id}
POST /api/tasks
POST /api/tasks/{task_id}/run
POST /api/tasks/{task_id}/retry
POST /api/tasks/{task_id}/cancel
GET  /api/tasks/{task_id}/context
POST /api/agents
GET  /api/agents/doctor
WS   /ws/events
```

Interactive FastAPI schema docs are available locally at:

```text
http://127.0.0.1:8787/api/docs
```

## Example flow

Initialize and create a task from the CLI:

```bash
arc init . --project-id demo
arc task create "Create the browser demo artifact" --file demo.txt
arc web --open
```

Inside the browser, select `T001` and press **RUN**. With the built-in `mock` profile as the default agent, ARC still performs a real repository change and the normal candidate/gate integration path.

To use Codex:

```bash
arc agent add builder --provider codex --role implementation --default
arc agent doctor builder
arc web --open
```

The browser RUN action uses the configured default agent profile.

## Deployment stance

`arc web` is intentionally a **local developer control surface** in v0.3, not a hosted multi-user server.

A future remote/distributed control plane should add at least authentication, authorization, CSRF/origin policy, secret isolation, TLS/reverse-proxy guidance, multi-project tenancy rules, persistent execution ownership, and stronger concurrency/lease semantics before it is presented as safe for network exposure.
