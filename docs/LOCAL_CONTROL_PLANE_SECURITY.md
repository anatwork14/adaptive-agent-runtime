# ARC Local Control-Plane Security

ARC 0.9.1 treats its browser applications as **privileged local developer control planes**, not ordinary websites.

`arc ui` can continue coding-agent sessions, start provider terminals, launch application previews, publish/synchronize review state, and submit candidates for integration. `arc web` can create tasks, configure agents, and start orchestration. These powers are distinct from ARC 0.9's worker-environment hardening: least-privilege provider environments reduce what worker processes inherit, while this policy protects the browser control plane itself.

## Current policy

Both browser control planes are strictly loopback-only:

```text
arc ui   → http://127.0.0.1:8788
arc web  → http://127.0.0.1:8787
```

Valid bind targets are explicit localhost names or literal loopback addresses such as:

```text
127.0.0.1
localhost
::1
```

Wildcard/public binds such as `0.0.0.0` and `::` are rejected. The historical `--allow-remote` option remains in the pre-alpha call surface only for compatibility with existing invocations; **it no longer bypasses the loopback restriction**. Authenticated remote mode is a separate future feature.

## Browser Origin boundary

Loopback binding prevents direct remote network exposure, but a malicious public page in the user's browser could still attempt requests to a localhost service. ARC therefore validates browser `Origin` headers on both control planes.

Accepted browser origins must use HTTP(S) plus an explicit localhost name or literal loopback IP, for example:

```text
http://127.0.0.1:8788
http://localhost:8788
http://[::1]:8788
```

ARC deliberately does not trust arbitrary DNS aliases merely because they happen to resolve to loopback. External, opaque, and DNS-alias origins are rejected, including:

```text
https://evil.example
http://loopback.example:8788
null
```

Non-browser/local API clients normally omit `Origin`; those requests remain supported. ARC therefore does **not** claim authentication against a hostile process already running as the same local OS user.

## WebSocket boundary

The event WebSocket applies the same Origin rule **before** accepting the connection. A non-local browser Origin is closed with WebSocket policy-violation code `1008` and does not receive the ARC event stream.

## Response hardening

Successful HTTP responses from the local browser control planes include:

```text
Cache-Control: no-store
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

These are defense-in-depth controls, not a substitute for authentication.

## Worker preview boundary

Worker previews remain separate browser origins:

```text
ARC Workspace   http://127.0.0.1:8788
worker preview  http://127.0.0.1:<worker-port>
```

ARC requires preview command templates to expose `{host}` and `{port}`, restricts preview binding to loopback, excludes provider credentials from preview environments under the 0.9 execution policy, and does not reverse-proxy untrusted preview content through the privileged Workspace origin.

## Relationship to ARC 0.9 execution security

ARC 0.9 introduced least-privilege worker environments. Provider processes receive a small runtime environment plus provider-scoped credentials and explicitly allowlisted variable names instead of inheriting the whole ARC host environment. Preview processes exclude provider credentials. Persistent tmux launches use a private single-use handoff so secret environment values do not need to appear in worker argv.

See [EXECUTION_SECURITY.md](EXECUTION_SECURITY.md) for that process/environment boundary. The browser Origin policy in this document is complementary; neither boundary replaces the other.

## What ARC 0.9.1 does **not** claim

ARC still does not provide:

- ARC-user authentication;
- authorization/RBAC;
- trusted remote access;
- multi-user tenant isolation;
- protection from a malicious process already running under the same local OS account;
- a sandbox for tmux/provider CLIs;
- complete provider filesystem/network isolation.

`tmux` is process-lifecycle infrastructure, not a security sandbox.

## Future authenticated remote mode

Remote access should be implemented as an explicit security feature, not restored with another bind flag. At minimum it should define:

```text
authenticated identity
        ↓
authorization / project scope
        ↓
CSRF + Origin policy
        ↓
secure transport / trusted proxy boundary
        ↓
WebSocket authorization
        ↓
audit trail + session revocation
```

Only after that boundary exists should ARC expose `arc ui` or `arc web` beyond loopback.

## Regression contract

ARC tests verify:

- IPv4 and IPv6 loopback classification;
- wildcard/public bind rejection;
- arbitrary DNS aliases are not accepted as local origins;
- the legacy remote opt-in cannot bypass local-only binding;
- hostile HTTP browser Origins receive `403`;
- explicit loopback browser Origins succeed;
- non-browser clients without `Origin` still work;
- hostile WebSocket Origins are rejected before event streaming;
- Workspace and Mission Control version metadata match the installed ARC 0.9.1 package metadata.
