# ARC Operator Guide

This guide documents the ARC v0.4 operator surface: vendor-native provider login, repository-local agent profiles, authoritative task lifecycle, live monitoring, terminal Mission Control, and browser Agent Orchestration Control.

## Operating model

Every ARC interface calls the same `ArcApplication` service boundary. The `Orchestrator` remains the single authoritative execution writer.

```text
                         ArcApplication
                               │
       ┌───────────────────────┼────────────────────────┐
       │                       │                        │
    CLI/Typer              TUI/Textual             FastAPI/Web
       │                       │                        │
       └───────────────────────┼────────────────────────┘
                               ▼
                          Orchestrator
                               │
             authoritative events + Git integration
```

Adaptive memory remains derived and non-authoritative.

Provider authentication is a separate boundary:

```text
arc login
    │
    ├── Codex native OAuth / credential store
    ├── Claude native OAuth / credential store
    └── Antigravity native Google OAuth / secure keyring

ARC stores: provider/profile metadata only
ARC does NOT store: access tokens, refresh tokens, OAuth codes, API keys
```

## Command map

```text
arc init
arc login [codex|claude|antigravity]
arc logout PROVIDER
arc auth status [PROVIDER]
arc auth login [PROVIDER]
arc auth logout PROVIDER

arc status
arc events
arc replay
arc run TASK
arc watch TASK
arc dashboard
arc web --open

arc task create
arc task list
arc task show
arc task run
arc task retry
arc task cancel

arc agent list
arc agent add
arc agent remove
arc agent doctor

arc config show
arc config default-agent

arc context build
arc context inspect
arc memory list
arc memory why
arc memory consolidate
arc memory rebuild-index
arc gate inspect
```

## Provider login

The normal setup path is:

```bash
arc login
```

When no provider is specified, ARC opens an interactive Textual picker using arrow-key navigation and Enter confirmation. After selection, the picker exits and ARC launches the provider CLI's own interactive authentication flow in the foreground.

Direct forms:

```bash
arc login codex --profile builder --default
arc login claude --profile reviewer
arc login antigravity --profile researcher
```

If the repository is initialized, ARC registers the named profile after provider login. Authentication material remains provider-owned.

Inspect status:

```bash
arc auth status
arc auth status codex
```

### Provider behavior

| Provider | Executable | ARC login delegation | Auth probe | ARC logout delegation |
|---|---|---|---|---|
| Codex | `codex` | `codex login` | `codex login status` | `codex logout` |
| Claude Code | `claude` | `claude auth login` | `claude auth status --text` | `claude auth logout` |
| Antigravity | `agy` | interactive `agy` first-run/session flow | authenticated `agy models` operation | not synthesized; use Antigravity's native `/logout` account control |

ARC intentionally does not inspect provider credential files or secure keyrings.

## Repository configuration

ARC stores non-secret configuration at:

```text
.arc/config.yaml
```

Example:

```yaml
project_id: my-project
default_agent: builder
hard_task_usd: 5.0
hard_project_usd: 500.0
visible_test_cmd:
  - python
  - -m
  - pytest
  - -q
agents:
  mock:
    name: mock
    provider: mock
    role: smoke-test
    enabled: true
  builder:
    name: builder
    provider: codex
    model: null
    role: implementation
    enabled: true
  reviewer:
    name: reviewer
    provider: claude
    model: null
    role: verification
    enabled: true
  researcher:
    name: researcher
    provider: antigravity
    model: null
    role: research
    enabled: true
```

`.arc/` is automatically added to repository-local `.git/info/exclude` so runtime metadata does not dirty the integration tree.

## Agent profiles and readiness

You may still configure a profile separately from login:

```bash
arc agent add builder --provider codex --role implementation --default
arc agent add reviewer --provider claude --role verification
arc agent add researcher --provider antigravity --role research
```

Provider-specific command overrides remain available where supported:

```bash
arc agent add builder --provider codex --command 'codex exec --full-auto -'
```

Environment overrides:

```bash
export ARC_CODEX_COMMAND='codex exec --full-auto -'
export ARC_CLAUDE_COMMAND='claude -p'
export ARC_OPENCODE_COMMAND='opencode run'
```

Check readiness:

```bash
arc agent doctor
arc agent doctor builder reviewer researcher
```

Doctor states:

| State | Meaning |
|---|---|
| `READY` | execution profile exists, CLI is installed, and native auth probe is healthy when supported |
| `AUTH_REQUIRED` | provider CLI exists but native authentication is not currently available |
| `MISSING` | provider executable is absent |
| `GATEWAY_ONLY` | gateway exists but is not a filesystem coding executor |
| `UNCONFIGURED` | required gateway configuration is absent |
| `DISABLED` | profile is disabled |

Auth probes are cached briefly so the browser dashboard does not repeatedly call provider account/status endpoints during normal refreshes.

OpenRouter intentionally remains `GATEWAY_ONLY`; ARC will not turn plain model completion into a fake repository patch.

## Antigravity execution

`AntigravityAgentAdapter` uses the real `agy` CLI in headless prompt mode. It does not parse textual output as a patch; ARC measures the actual Git worktree changes after the provider returns, just as it does for other real coding-agent adapters.

Authentication must be completed interactively at least once before headless execution can work.

## Task lifecycle

Create:

```bash
arc task create "Implement authentication middleware" \
  --file src/auth.py \
  --file tests/test_auth.py \
  --accept "authentication tests pass" \
  --risk 0.6
```

Dependencies:

```bash
arc task create "Add authentication tests" --depends T001 --file tests/test_auth.py
```

Inspect:

```bash
arc task list
arc task show T001
```

Execute:

```bash
arc run T001 --agent builder
# equivalent
arc task run T001 --agent builder
```

Only `READY` tasks execute. The normal path remains:

```text
bounded immutable context
        ↓
isolated Git worktree
        ↓
real provider or explicit mock
        ↓
immutable candidate commit
        ↓
fresh verification worktree
        ↓
serialized integration gate
        ↓
integration branch
```

Retry appends `recovery.retry`:

```bash
arc task retry T001 --reason "provider recovered"
```

Cancel appends `task.abandoned`:

```bash
arc task cancel T001 --reason "scope removed"
```

## Live monitoring

```bash
arc watch T001
```

The view follows authoritative state/events until `completed`, `failed`, or `abandoned`.

The shared application layer also exposes `EventStream.poll()` and async `EventStream.subscribe()`.

## Terminal Mission Control

```bash
arc dashboard
```

Keyboard actions:

| Key | Action |
|---|---|
| `g` | execute selected READY task with the configured default agent |
| `y` | retry selected failed/blocked task |
| `x` | cancel selected unfinished task |
| `r` | force refresh |
| `q` | quit |

The TUI consumes `ArcApplication`; it owns no parallel database.

## Browser Agent Orchestration Control

Launch:

```bash
arc web --open
```

The browser is inspired by orchestration dashboards rather than CRUD admin UIs. The main hierarchy is:

```text
ARC Root + provider orchestrators
          ↓
real runtime analytics
          ↓
live task execution ledger
          ↓
provider-grouped agent teams
          ↓
mission inspector + authoritative event trace
```

Provider cards for Codex, Claude, and Antigravity show real configured-profile/readiness state. If a provider is not configured or requires auth, the card surfaces a copyable terminal command such as:

```bash
arc login codex --profile codex
```

The browser does not execute OAuth and never accepts provider credentials.

The circular activity indicator is based only on ARC-local assigned/running work. It is **not** a fabricated provider quota, usage-limit, or rate-limit metric.

Web Mission Control remains localhost-first. Non-loopback binding still requires explicit `--allow-remote`; remote-user authentication/authorization is not yet a production boundary.

## Context inspection

```bash
arc context inspect T001 --agent builder
```

The output includes immutable context ID/digest, authoritative state version, token count, derived memory categories, and code-evidence count. Risk may change allocation but never expands the hard task token ceiling.

## Memory and gate inspection

```bash
arc memory list
arc memory why M_44
arc memory consolidate
arc memory rebuild-index
arc gate inspect T001
```

A rejected candidate is not promoted to durable project memory.

## Deterministic replay

```bash
arc replay
```

Replay rebuilds project/task/budget/lease projections from authoritative events. Recorded materialized memory is replayed as data rather than regenerated by an LLM.

## Safety boundaries

ARC executes agent-produced code. Provider CLI execution remains experimental host-mode even though command/test execution can use Docker isolation. Use disposable or protected working environments for untrusted tasks.

Provider credentials remain in vendor-owned stores. ARC's repository config must stay non-secret.
