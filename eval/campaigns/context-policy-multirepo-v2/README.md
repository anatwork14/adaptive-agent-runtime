# Context Policy Multi-Repository Study V2 Proposal

This directory contains the proposed V2 preregistration and apparatus
hardening record. It is not a frozen campaign and must be independently
reviewed before any V2 freeze or provider-backed benchmark execution.

V2 preserves the V1 scientific design: the same Click, HTTPX, and
python-dotenv commits; the same T001→T002→T003 sequences; B3, B5, and B7; six
repetitions; the same task/project budgets; the same hidden-test tree digests;
and the same hierarchical analysis parameters. The campaign ID is new so
`context-policy-multirepo-v2/a001` cannot be confused with the immutable
`context-policy-multirepo-v1/a001` failure.

The only proposed scientific-runtime change is explicit use of the documented
Codex `exec --json` JSONL output mode for lifecycle observability. The primary
apparatus changes are durable sanitized provider diagnostics, return-code and
bounded-tail persistence, conservative failure classification, lifecycle
telemetry, deterministic fake-provider tests, and passive/active provider
qualification.

The target-environment qualification uses repository-specific Docker harnesses
with local image IDs recorded as immutable `sha256:` identities. Click uses its
locked `uv` environment on CPython 3.10; HTTPX uses its declared requirements
on CPython 3.11 and excludes only tests marked `network` because the sandbox
has no network; and python-dotenv uses its declared requirements on CPython
3.10. The exact commands, image identities, non-secret environment, import
proofs, and qualification IDs are recorded in the contract and review packet.

The gate consumes the harness directly after candidate cherry-pick. The
candidate is mounted read-write, the hidden suite is mounted separately
read-only, and no provider process receives the hidden mount.

## Freeze prerequisites

Before freezing, complete all checks in `campaign_contract.json` and record the
external active-probe result. The active probe must use no benchmark task,
target repository, hidden test, or benchmark result directory. It is an
apparatus qualification artifact and never scientific evidence.

Do not authenticate or run V2 benchmark inference merely because this proposal
exists. Freeze only after independent review of the implementation diff,
tests, qualification result, repository/environment checks, and exact ARC
commit.
