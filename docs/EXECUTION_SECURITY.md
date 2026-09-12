# ARC Execution Security

ARC 0.9 introduces a least-privilege environment policy for processes that execute coding-agent or repository workloads.

The goal is narrow and explicit:

> **A worker should not inherit unrelated host environment secrets merely because ARC launched it.**

This is a reduction of ambient authority. It is **not** a full provider sandbox.

## Threat addressed

Python subprocess APIs inherit the parent environment unless an explicit `env` mapping is supplied. A development shell may contain credentials unrelated to the active worker, for example:

```text
AWS_SECRET_ACCESS_KEY
DATABASE_URL
SENTRY_AUTH_TOKEN
GITHUB_TOKEN
ANTHROPIC_API_KEY
OPENAI_API_KEY
```

Before 0.9, a provider process or tmux-owned preview could receive the whole environment even when it needed only `PATH`, `HOME`, and its own provider authentication context.

ARC 0.9 constructs an explicit environment instead.

## Execution policy

Every ARC-managed worker execution starts from a small base set of process/runtime variables such as:

```text
PATH
HOME
USER
SHELL
LANG / locale
TERM
TMPDIR
XDG_* directories
certificate bundle variables
```

ARC then adds provider-specific variables for the selected provider only.

Examples:

```text
Codex       → OPENAI_API_KEY, OPENAI_BASE_URL, ...
Claude      → ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ...
Antigravity → GOOGLE_API_KEY, GEMINI_API_KEY, ...
OpenRouter  → OPENROUTER_API_KEY
```

A Codex worker therefore does not automatically receive an Anthropic key, AWS credentials, a database URL, or arbitrary tokens that happen to exist in the parent shell.

Provider CLIs that authenticate through their own files/keyrings under `HOME` remain provider-owned. ARC does not copy those credentials into `.arc/`.

## Explicit additional variables

An agent profile may opt in extra environment variable **names**:

```yaml
agents:
  builder:
    name: builder
    provider: codex
    env_allow:
      - INTERNAL_REGISTRY_HOST
      - CUSTOM_TOOL_HOME
```

Only names are stored. ARC reads the current values from the host environment when the worker starts.

Do **not** write secret values into `.arc/config.yaml`.

This means the persisted ARC profile can say:

```text
forward CUSTOM_TOOL_HOME
```

but it does not contain:

```text
CUSTOM_TOOL_HOME=/some/private/value
```

Environment names are validated and deduplicated when the profile is loaded.

## Persistent tmux runtimes

A tmux server may outlive the ARC process that created it. That creates a subtle risk: the tmux server itself can retain an older, broader environment.

ARC 0.9 therefore launches persistent terminal/preview commands through a clean boundary:

```text
env -i KEY=value KEY=value ... actual-command
```

The worker receives the ARC-built environment rather than whatever happens to be stored in the long-lived tmux server.

## Provider terminal

These routes use the same provider-scoped environment policy:

```text
arc session send ...
arc terminal SESSION
arc attach SESSION
```

The profile's provider defaults and `env_allow` names are applied consistently.

## Application preview

Worker previews are treated more strictly.

A preview receives only the generic runtime environment. ARC does **not** inject provider credentials into arbitrary development servers.

```text
worker preview
  ├── PATH / HOME / locale / runtime plumbing
  └── no automatic OpenAI / Anthropic / Google / OpenRouter keys
```

A project framework may still deliberately load repository-local configuration such as its own `.env` file. That is repository behavior, not ambient injection by ARC.

Preview binding remains loopback-only.

## Auditing without persisting values

Runtime and agent traces may record:

```json
{
  "environment_keys": ["HOME", "PATH", "OPENAI_API_KEY"]
}
```

They do not record the associated values.

Obvious secret-valued command-line arguments are also redacted before command traces/events are written.

## Authentication commands are different

`arc login`, `arc logout`, and provider authentication probes are provider-owned control-plane operations. They are not repository workload execution and are intentionally not governed by the same worker environment policy.

ARC still does not store the resulting OAuth/session credentials.

## What this does not solve

Environment isolation is not an operating-system sandbox.

A host-mode coding agent still runs with the filesystem and network permissions of the user who launched ARC. Depending on provider behavior, it may be able to access:

- files elsewhere under the user's home directory;
- provider-owned credential/keyring files;
- the network;
- local sockets/services accessible to that user.

Therefore ARC 0.9 does **not** claim:

- full provider process sandboxing;
- filesystem isolation outside the Git worktree;
- provider network isolation;
- authenticated remote Workspace access;
- remote multi-user RBAC.

Those remain separate hardening milestones.

## Security invariant

Least-privilege execution does not change ARC's correctness boundary:

```text
worker output / terminal / preview
             ↓
       isolated draft
             ↓
      exact Git candidate
             ↓
      IntegrationGate
             ↓
       gate.accepted
```

A running process, successful model response, or green preview never becomes authoritative project state by itself.
