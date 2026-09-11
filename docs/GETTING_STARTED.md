# ARC Getting Started

ARC exposes one runtime through the CLI, terminal Mission Control, and localhost browser Agent Orchestration Control. You do not need to write Python to configure providers or run tasks.

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

## 3. Connect a coding-agent account

Run:

```bash
arc login
```

ARC opens an arrow-key login picker:

```text
ARC  ·  CONNECT PROVIDER

Select login method

> OpenAI Codex    · ChatGPT / OpenAI OAuth
  Claude Code     · Anthropic OAuth
  Antigravity     · Google OAuth

↑/↓ Navigate   Enter Confirm   Esc Cancel
```

After you choose a provider, ARC exits the picker and invokes the **provider's own native authentication flow** in the foreground. ARC does not receive, copy, or persist OAuth tokens.

You can skip the picker:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
```

When the current repository is already initialized, `--profile` registers the authenticated provider as an ARC agent profile after login. Credentials remain in the provider CLI's own credential/keyring store.

Inspect account state at any time:

```bash
arc auth status
arc auth status codex
```

Typical states are:

```text
AUTHENTICATED
SIGNED_OUT
MISSING
UNKNOWN
```

ARC's agent doctor also distinguishes installation from authentication:

```bash
arc agent doctor
```

Typical execution states are:

```text
READY
AUTH_REQUIRED
MISSING
GATEWAY_ONLY
DISABLED
```

### Supported native login flows

| Provider | ARC profile provider | Native auth |
|---|---|---|
| OpenAI Codex | `codex` | ChatGPT / OpenAI OAuth |
| Claude Code | `claude` | Anthropic OAuth |
| Google Antigravity | `antigravity` | Google OAuth / secure keyring |

`opencode` remains available as a CLI execution provider, and `openrouter` remains gateway-only until ARC owns a filesystem tool loop for it.

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

Every project still starts with the deterministic `mock` profile so ARC itself can be validated without provider cost:

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

## 6. Run with a connected provider

If you used:

```bash
arc login codex --profile builder --default
```

then:

```bash
arc agent doctor builder
arc run T001 --agent builder
```

For Claude or Antigravity, use the profile name you registered.

ARC does not fabricate provider success. Missing executables, missing authentication, provider failures, or empty repository edits surface as failures instead of silently falling back to the mock adapter.

## 7. Watch a mission live

In another terminal:

```bash
arc watch T001
```

`arc watch` reads the same append-only authoritative event stream used by replay and both Mission Control interfaces.

## 8. Open terminal Mission Control

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

## 9. Open browser Agent Orchestration Control

```bash
arc web --open
```

Then open:

```text
http://127.0.0.1:8787
```

The redesigned UI is orchestration-first rather than a generic admin dashboard. It provides:

- ARC Root + Codex + Claude + Antigravity orchestrator cards;
- real provider/profile readiness and authentication states;
- live task execution ledger;
- agent teams grouped by provider, with running vs idle workers;
- real ARC state/budget/memory metrics;
- mission inspector and context inspection;
- authoritative WebSocket event stream;
- copyable `arc login ...` commands when a provider needs connection.

The activity rings represent **ARC local workload share**, not fabricated provider quota or rate-limit data.

The browser never accepts provider API keys or OAuth tokens. Native interactive login remains a terminal/provider responsibility.

The web control plane is intentionally localhost-only by default. ARC refuses a non-loopback bind unless you explicitly supply `--allow-remote`; the current UI has no built-in remote-user authentication.

See [`WEB_MISSION_CONTROL.md`](WEB_MISSION_CONTROL.md) for API and security details.

## 10. Inspect what ARC used

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

For the full operator command reference and configuration format, see [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md).
