# ARC Getting Started

ARC exposes the normal operator flow directly through the CLI, terminal Mission Control, and a localhost browser Mission Control. You do not need to write Python just to create and run a task.

## 1. Install

```bash
git clone https://github.com/anatwork14/adaptive-agent-runtime.git
cd adaptive-agent-runtime
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
arc --help
```

Requirements: Python 3.11+, Git, and a clean Git repository for the project ARC will operate on.

## 2. Initialize a project

From the target repository:

```bash
arc init . --project-id demo
arc status
```

ARC writes local runtime state under `.arc/` and automatically adds `.arc/` to the repository-local Git exclude file (`.git/info/exclude`). It does not force a committed `.gitignore` change.

## 3. Check available agents

Every initialized project starts with a deterministic `mock` profile for zero-credential smoke tests.

```bash
arc agent list
arc agent doctor
```

Add a real provider profile after installing and authenticating its CLI:

```bash
arc agent add builder \
  --provider codex \
  --role implementation \
  --default

arc agent doctor builder
```

Other supported profile providers are `claude` and `opencode`. `openrouter` remains gateway-only until ARC has a filesystem tool loop for it.

## 4. Create a task

```bash
arc task create "Create a traceable ARC demo artifact" \
  --file arc_demo.txt \
  --accept "artifact integrates through the gate" \
  --risk 0.2
```

ARC auto-generates task IDs (`T001`, `T002`, ...). Inspect the DAG with:

```bash
arc task list
arc task show T001
```

## 5. Run a zero-credential smoke task

```bash
arc run T001 --agent mock
```

This is not a fake gate result. `MockAgentAdapter` makes a deterministic repository edit, then ARC uses the normal execution path:

```text
ContextPacket
    ↓
Git worktree
    ↓
candidate commit
    ↓
fresh verification worktree
    ↓
static checks / configured tests
    ↓
transactional integration gate
    ↓
integration branch
```

The mock profile exists to validate ARC itself without spending provider tokens.

## 6. Watch a mission live

In another terminal:

```bash
arc watch T001
```

`arc watch` reads the same append-only authoritative event stream used by replay and both Mission Control interfaces.

## 7. Open terminal Mission Control

```bash
arc dashboard
```

Keyboard controls:

```text
r  refresh
g  run selected READY task
y  retry selected failed/blocked task
x  cancel selected task
q  quit
```

The Textual TUI shows the task DAG, configured agents and readiness, project/budget state, active memory, task detail, and a live authoritative event log.

## 8. Open browser Mission Control

```bash
arc web --open
```

Then open:

```text
http://127.0.0.1:8787
```

The browser UI exposes the same project/task state plus interactive task creation, run/retry/cancel controls, context inspection, named agent profiles, and a live WebSocket event stream.

It is intentionally localhost-only by default. ARC refuses a non-loopback bind unless you explicitly supply `--allow-remote`; the current UI has no built-in authentication, so do not expose it directly to an untrusted network.

See [`WEB_MISSION_CONTROL.md`](WEB_MISSION_CONTROL.md) for API and security details.

## 9. Inspect what ARC used

```bash
arc events
arc replay
arc context inspect T001 --agent mock
arc gate inspect T001
arc memory list
```

For a specific memory:

```bash
arc memory why M_44
```

## 10. Run with Codex

After `arc agent doctor builder` reports `READY`:

```bash
arc task create "Implement the requested repository change" \
  --file src/example.py \
  --accept "tests pass"

arc run T002 --agent builder
```

ARC does not fabricate provider success. If the Codex executable is missing or the provider process fails, the task execution fails explicitly.

For the full operator command reference and configuration format, see [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).
