# Security Policy

ARC is experimental/pre-alpha software that executes code produced by AI coding agents. Treat generated commands, patches, tests, dev servers, and provider processes as potentially untrusted.

## Supported security posture

The current development line is ARC **0.8.x**. Security fixes are applied to `main`; older pre-alpha snapshots are not maintained as separate supported release branches.

## Reporting a vulnerability

Please avoid publishing exploit details in a public issue before maintainers have had a reasonable opportunity to investigate.

Use GitHub's private security-advisory / vulnerability-reporting flow for this repository when available. If private reporting is unavailable, open a minimal public issue asking for a private contact channel without including exploit details, credentials, tokens, private repository content, or other sensitive data.

A useful report should include:

- affected ARC version/commit;
- operating system and Python version;
- affected command or interface (`arc`, `arc ui`, `arc web`, runtime/preview, gate, etc.);
- required preconditions;
- reproducible steps using non-sensitive test data;
- security impact;
- whether the issue crosses ARC's documented trust boundaries.

## Browser control planes

`arc ui` and `arc web` are privileged **local-only** developer control planes. They can mutate ARC/project state and must not be exposed as general web services.

ARC 0.8.1 enforces:

- loopback-only binding;
- the legacy `--allow-remote` flag cannot bypass that restriction;
- browser HTTP Origin validation;
- WebSocket Origin validation before accepting the event stream;
- explicit localhost/literal-loopback matching rather than trusting arbitrary DNS aliases;
- conservative `no-store`, `nosniff`, and no-referrer response headers.

ARC does **not** yet provide ARC-user authentication, authorization/RBAC, trusted remote access, or multi-user isolation. A malicious process already executing under the same local OS account is outside the current browser-origin protection boundary.

See [`docs/LOCAL_CONTROL_PLANE_SECURITY.md`](docs/LOCAL_CONTROL_PLANE_SECURITY.md) for the detailed threat model.

## Worker previews

Application previews run from isolated worker worktrees but are still application code generated or modified by agents. ARC restricts preview binding to loopback and keeps preview content on a separate browser origin rather than reverse-proxying it through the privileged Workspace origin.

Do not treat a preview as trusted merely because it runs on localhost.

## Provider and GitHub credentials

ARC delegates authentication to the tools that own it:

- provider credentials remain in provider CLI/keyring storage;
- GitHub credentials remain owned by `gh`;
- ARC does not intentionally copy provider/GitHub tokens into `.arc/`, browser payloads, or authoritative events;
- obvious secret-valued runtime command arguments are redacted before runtime metadata is persisted.

Provider coding CLIs currently run in experimental host mode. Safely brokering provider credentials into isolated containers remains future work.

## Process isolation

`tmux` is a process-lifecycle mechanism, **not a sandbox**.

ARC's command/test execution path can use its Docker-backed sandbox with network/capability/resource restrictions, but that does not imply every provider process, preview, or developer integration runs inside the same isolation boundary.

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

Do not place real secrets in:

- task goals or prompts when avoidable;
- committed ARC configuration;
- preview command-line arguments;
- test fixtures checked into the repository;
- issue/PR logs;
- screenshots or public bug reports.

Use provider-native credential stores and environment/secret-management mechanisms appropriate to your development environment.
