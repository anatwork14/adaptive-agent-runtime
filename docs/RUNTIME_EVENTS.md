# ARC Runtime Event Contract

ARC 0.8 records live runtime supervision as replayable operational events without making process liveness authoritative project state.

| Event | Meaning |
|---|---|
| `session.runtime_started` | ARC requested a named runtime for a worker terminal or preview. |
| `session.runtime_stopped` | ARC terminated that named managed runtime. |
| `session.terminal_attached` | An operator attached to a persistent provider terminal. |

A `session.runtime_started` payload may contain:

```text
session_id
runtime_kind       terminal | preview
backend            tmux
runtime_name
sanitized command argv
workspace
host
port
url
```

Command metadata is sanitized before persistence for obvious secret-valued arguments. Runtime events never establish whether a task is complete; the integration gate remains the authoritative completion boundary.

Runtime liveness is reconstructed as:

```text
latest unmatched runtime-start metadata
                +
current tmux named-session existence
                =
operational running projection
```

If tmux or the child process disappears, historical events remain intact while current runtime status becomes non-running.
