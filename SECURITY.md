# Security Policy

ARC is experimental/pre-alpha software that executes code produced by AI coding agents. Treat generated commands, patches, tests, dev servers, provider processes, and provider output as potentially untrusted.

## Supported security posture

The current development line is ARC **0.16.x**. Security fixes are applied to `main`; older pre-alpha snapshots are not maintained as separate supported release branches. The `0.16.0` software/apparatus release does not represent a successful V7 scientific result; V7/a001 remains incomplete with forensic closure pending.

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

## Supervised live turns

The 0.10-era live-turn implementation can start a provider subprocess from the Workspace, stream its stdout/stderr through ARC events, and cancel it explicitly. This improves observability but does **not** make the provider process authoritative or sandboxed.

Before provider output becomes durable or reaches the Workspace WebSocket, ARC masks values of credential-like environment variables forwarded to that process and common provider-token forms. The final provider summary and stderr failure tail use the same redacted text. This is defense in depth, not a complete data-loss-prevention system; an agent can still intentionally emit sensitive repository content that does not match those redaction rules.

A browser-started live turn owns the same per-worker action lock as review/runtime/submit operations. Worker stop requests cancellation, waits for the supervised provider to exit, and only then removes the worktree. Workspace shutdown also requests cancellation of supervised turns. If a provider ignores normal termination, ARC escalates to process kill.

After an ARC restart, a historical `session.turn_started` event does not prove the provider process is still alive. ARC does not automatically launch a duplicate turn; recovery is explicit through the surviving worktree/session.

See [`docs/LIVE_TURNS.md`](docs/LIVE_TURNS.md) for the exact lifecycle and restart semantics.

## Worker previews

Application previews run from isolated worker worktrees but are still application code generated or modified by agents. ARC restricts preview binding to loopback and keeps preview content on a separate browser origin rather than reverse-proxying it through the privileged Workspace origin.

Do not treat a preview as trusted merely because it runs on localhost.

## Provider and GitHub credentials

ARC delegates authentication to the tools that own it:

- provider credentials remain in provider CLI/keyring storage;
- GitHub credentials remain owned by `gh`;
- ARC does not intentionally copy provider/GitHub tokens into `.arc/` or browser configuration payloads;
- runtime audit data stores environment-variable names, not values;
- obvious secret-valued command arguments are redacted before persisted runtime metadata is emitted;
- streamed provider output is redacted before ARC persists it as `session.turn_output` or includes it in provider summaries.

## Process isolation

`tmux` and Workspace live-turn supervision are process-lifecycle mechanisms, **not sandboxes**.

ARC's command/test execution path can use its Docker-backed sandbox with network/capability/resource restrictions. Provider coding CLIs remain experimental host-mode integrations, and ARC's environment filtering does not imply complete filesystem or network isolation.

Review the exact execution path before using ARC with sensitive repositories or credentials.

## Authoritative-state boundary

ARC's correctness model also serves as a security boundary:

```text
chat / provider output / memory / PR / preview / terminal / external CI
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

A successful agent turn, streamed “done” message, cancelled turn, green pull request, running preview, or external review approval must not bypass the exact-candidate IntegrationGate.

## Secrets

Do not place real secrets in task prompts when avoidable, committed ARC configuration, preview command-line arguments, checked-in test fixtures, issue/PR logs, screenshots, or public bug reports. Use provider-native credential stores and appropriate environment/secret-management mechanisms.
