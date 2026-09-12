# ARC 0.9 Release Checklist

## Least-privilege execution

- [x] explicit child-process environment construction
- [x] provider-scoped default credential variables
- [x] unrelated host secrets excluded by default
- [x] profile `env_allow` stores variable names only
- [x] `arc env-policy` inspect/set/clear surface
- [x] profile-local command overrides no longer mutate global `os.environ`
- [x] direct provider subprocess receives explicit `env=`
- [x] Antigravity receives the same explicit environment boundary
- [x] native `arc attach` receives the same explicit environment boundary

## Persistent runtimes

- [x] terminal runtime receives provider-scoped environment
- [x] application preview receives base runtime environment only
- [x] tmux server ambient environment is not trusted
- [x] environment values do not appear in tmux worker argv
- [x] mode-0600 single-use environment handoff
- [x] handoff deleted before long-lived worker `execve`
- [x] handoff removed by ARC when tmux session creation fails
- [x] runtime events store environment names only
- [x] obvious secret-valued command arguments redacted in traces/events

## Correctness / compatibility

- [x] authoritative task/Git/gate boundary unchanged
- [x] persistent runtime replay semantics unchanged
- [x] preview loopback restriction unchanged
- [x] Workspace runtime mutation locking unchanged
- [x] package version 0.9.0
- [x] Workspace API metadata 0.9.0
- [x] execution-security documentation

## Explicit non-goals

ARC 0.9 does **not** claim:

- provider filesystem sandboxing;
- provider network isolation;
- remote Workspace authentication/RBAC;
- full secret scanning of provider stdout/stderr;
- containerized provider credential brokering.

Environment isolation reduces ambient authority; it is not an OS sandbox.

## Release gates

- [ ] exact frozen branch CI green on Python 3.11 + 3.12
- [ ] pull-request-triggered CI green on the exact PR head
- [ ] squash merge with expected head SHA
- [ ] post-merge `main` CI green
- [ ] Pages deployment green if documentation changes trigger it

Do not mark the release gates complete until GitHub verifies the exact corresponding revision.
