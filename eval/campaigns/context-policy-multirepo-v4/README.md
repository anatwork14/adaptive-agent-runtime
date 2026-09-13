# ARC V4 — Context-policy multirepo timeout-hardening campaign

V1, V2, and V3 are closed. This proposed V4 apparatus preserves the V3
scientific core and changes exactly one protocol variable: the ARC provider/
agent execution timeout increases from 180 seconds to 600 seconds. The Docker
visible and hidden test harness timeout remains 180 seconds. This is a
treatment-neutral apparatus change intended to avoid artificial right
censoring of provider turns; it is not a claim that the scientific protocol is
unchanged.

The V3 result and failure classification are preserved in `V3_POSTMORTEM.md`.
Every timeout source and its scientific scope is enumerated in
`V4_TIMEOUT_AUDIT.md`. The machine-readable V3-to-V4 protocol diff records the
single intended timeout change.

V4 also hermetically binds the Codex provider to the dedicated home
`/Users/teobun/arc-secure/codex-v4-home` and its non-secret `config.toml`
digest. Authentication, version checks, provider qualification, terminal
launches, and real provider subprocesses inject this home explicitly; ambient
`CODEX_HOME` is not trusted. Authentication state and credential files remain
outside the review bundle.

Before any canonical freeze, the apparatus qualification must pass the ARC
suite, hostile Git configuration and identity-environment regressions, the
provider-free synthetic workflow, and passive/active non-benchmark provider
qualification. The qualification must not load hidden tests into provider
context and must not create a V4 benchmark attempt.

The intended freeze command is `freeze_campaign.py`, and the intended runtime
boundary is `execute_campaign.py`. Neither is run as part of this apparatus
hardening review. The offline `finalize_campaign.py` is reserved for a future
successful V4 attempt and performs no provider inference.
