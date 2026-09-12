# Security Policy

ARC is experimental/pre-alpha software that executes code produced by AI coding agents. Treat generated commands, patches, tests, dev servers, and provider processes as potentially untrusted.

## Supported security posture

The current development line is ARC **0.9.x**. Security fixes are applied to `main`; older pre-alpha snapshots are not maintained as separate supported release branches.

## Reporting a vulnerability

Please avoid publishing exploit details in a public issue before maintainers have had a reasonable opportunity to investigate.

Use GitHub's private security-advisory / vulnerability-reporting flow for this repository when available. If private reporting is unavailable, open a minimal public issue asking for a private contact channel without including exploit details, credentials, tokens, private repository content, or other sensitive data.

A useful report should include the affected ARC version/commit, operating system/Python version, affected command or interface, required preconditions, reproducible non-sensitive steps, impact, and the trust boundary crossed.

## Browser control planes

`arc ui` and `arc web` are privileged **local-only** developer control planes. They can mutate ARC/project state and must not be exposed as general web services.

ARC 0.9.1 enforces:

- loopback-only binding;
- the legacy `--allow-remote` flag cannot bypass that restriction;
- browser HTTP Origin validation;
- WebSocket Origin validation before accepting the event stream;
- explicit localhost/literal-loopback matching rather than trusting arbitrary DNS aliases;
- conservative `no-store`, `nosniff`, and no-referrer response headers.

ARC does **not** yet provide ARC-user authentication, authorization/RBAC, trusted remote access, or multi-user isolation. A malicious process already executing under the same local OS account is outside the current browser-origin protection boundary.

See [`docs/LOCAL_CONTROL_PLANE_SECURITY.md`](docs/LOCAL_CONTROL_PLANE_SECURITY.md) for the detailed browser threat model.

## Worker execution environment

ARC 0.9 introduced least-privilege environment propagation for worker/provider subprocesses. Provider profiles receive a small runtime environment plus provider-scoped credential variables and explicitly allowlisted extra names rather than inheriting the entire ARC host environment. Preview environments exclude provider credentials, and persistent tmux startup uses a private single-use environment handoff.

See [`docs/EXECUTION_SECURITY.md`](docs/EXECUTION_SECURITY.md) for the exact environment policy and limitations.

## Worker previews

Application previews run from isolated worker worktrees but are still application code generated or modified by agents. ARC restricts preview binding to loopback and keeps preview content on a separate browser origin rather than reverse-proxying it through the privileged Workspace origin.

Do not treat a preview as trusted merely because it runs on localhost.

## Provider and GitHub credentials

ARC delegates authentication to the tools that own it:

- provider credentials remain in provider CLI/keyring storage;
- GitHub credentials remain owned by `gh`;
- ARC does not intentionally copy provider/GitHub tokens into `.arc/`, browser payloads, or authoritative events;
- runtime audit data stores environment-variable names, not values;
- obvious secret-valued command arguments are redacted before persisted runtime metadata is emitted.

## Process isolation

`tmux` is a process-lifecycle mechanism, **not a sandbox**.

ARC's command/test execution path can use its Docker-backed sandbox with network/capability/resource restrictions. Provider coding CLIs remain experimental host-mode integrations, and ARC 0.9's environment filtering does not imply complete filesystem or network isolation.

Review the exact execution path before using ARC with sensitive repositories or credentials.

## Authoritative-state boundary

ARC's correctness model also serves as a security boundary:

```text
chat / memory / PR / preview / terminal / external CI
                    │
                    ▼
           operational context only
                    │
                    ▼
             exact Git candidate
                    │
                    ▼
             IntegrationGate
                    │
                    ▼
          authoritative project state
```

A successful agent turn, green pull request, running preview, or external review approval must not bypass the exact-candidate IntegrationGate.

## Secrets

Do not place real secrets in task prompts when avoidable, committed ARC configuration, preview command-line arguments, checked-in test fixtures, issue/PR logs, screenshots, or public bug reports. Use provider-native credential stores and appropriate environment/secret-management mechanisms.
