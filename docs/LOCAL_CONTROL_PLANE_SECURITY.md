# ARC Local Control-Plane Security

ARC 0.8.1 treats its browser applications as **privileged local developer control planes**, not ordinary websites.

`arc ui` can continue coding-agent sessions, start provider terminals, launch application previews, publish and synchronize review state, and submit candidates for integration. `arc web` can create tasks, configure agents, and start orchestration. Until ARC has an authenticated remote/multi-user design, exposing either surface beyond the local machine would create an unnecessarily broad authority boundary.

## Current policy

Both browser control planes are loopback-only:

```text
arc ui   → http://127.0.0.1:8788
arc web  → http://127.0.0.1:8787
```

Valid bind targets are loopback addresses/names such as:

```text
127.0.0.1
localhost
::1
```

Wildcard/public binds such as these are rejected:

```text
0.0.0.0
::
```

The historical `--allow-remote` option remains in the pre-alpha CLI/API only for compatibility with existing invocations. **It no longer bypasses the loopback restriction.** Authenticated remote mode is a separate future feature.

## Browser Origin boundary

Binding to loopback prevents direct remote network exposure, but a malicious public web page running in the user's browser could still try to send requests to a localhost service.

ARC therefore validates browser `Origin` headers on both local control planes.

Accepted browser origins must use HTTP(S) and resolve entirely to loopback, for example:

```text
http://127.0.0.1:8788
http://localhost:8788
http://[::1]:8788
```

External or opaque origins are rejected, for example:

```text
https://evil.example
null
```

Non-browser/local API clients normally omit `Origin`; those requests remain supported. This is intentional and means ARC does **not** claim local-process authentication. A hostile process already running as the same user is outside this browser-origin protection boundary.

## WebSocket boundary

The event WebSocket applies the same Origin rule **before** accepting the connection. A non-loopback browser Origin is closed with policy-violation code `1008` and does not receive the ARC event stream.

## Response hardening

Successful HTTP responses from the local browser control planes include conservative local-control-plane headers:

```text
Cache-Control: no-store
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
```

These headers reduce accidental caching/content interpretation/referrer leakage. They are defense-in-depth; they are not a substitute for authentication.

## Worker preview boundary

Worker application previews are separate from the ARC control plane:

```text
ARC Workspace   http://127.0.0.1:8788
worker preview  http://127.0.0.1:<worker-port>
```

ARC requires preview command templates to contain both `{host}` and `{port}` so ARC controls the endpoint, and preview hosts are also restricted to loopback. Preview application content is loaded directly from its own origin rather than reverse-proxied through the privileged Workspace origin.

A preview is untrusted application output. It does not gain ARC control-plane authority merely because it runs on localhost.

## Credential boundary

This patch does not change ARC's credential model:

- provider credentials remain owned by provider CLIs/keyrings;
- GitHub credentials remain owned by `gh`;
- ARC does not copy those credentials into `.arc/`, browser payloads, or runtime events;
- obvious secret-valued runtime command arguments are redacted before event persistence.

## What ARC 0.8.1 does **not** claim

ARC still does not provide:

- ARC-user authentication;
- authorization/RBAC;
- trusted remote access;
- multi-user tenant isolation;
- protection from a malicious process already running under the same local OS account;
- a sandbox for tmux/provider CLIs;
- a completed provider credential/container isolation boundary.

`tmux` is process-lifecycle infrastructure, not a security sandbox. Provider coding CLIs remain experimental host-mode integrations.

## Future authenticated remote mode

Remote access should not be restored with another bind flag. It should be designed as an explicit security feature with, at minimum:

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

ARC's test suite now verifies:

- IPv4 and IPv6 loopback classification;
- wildcard/public bind rejection;
- the legacy remote opt-in cannot bypass local-only binding;
- hostile HTTP browser Origins receive `403`;
- loopback browser Origins succeed;
- non-browser clients without `Origin` still work;
- hostile WebSocket Origins are rejected before event streaming;
- Workspace and Mission Control version metadata match the 0.8.1 security patch.
