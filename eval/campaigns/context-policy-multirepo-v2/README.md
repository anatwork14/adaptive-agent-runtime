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

The target-environment qualification selected repository-specific visible-test
harnesses. Click uses its locked `uv`/`tox` test environment; HTTPX uses its
declared requirements in Python 3.11 with the fixed macOS Trio teardown-warning
filter; and python-dotenv uses its declared requirements in Python 3.10 with
the candidate venv and GNU `printenv` first on `PATH`. The exact identifiers,
commands, import-path proofs, and platform caveats are recorded in
`V2_TARGET_ENVIRONMENT_QUALIFICATION.md` and in the contract.

## Freeze prerequisites

Before freezing, complete all checks in `campaign_contract.json` and record the
external active-probe result. The active probe must use no benchmark task,
target repository, hidden test, or benchmark result directory. It is an
apparatus qualification artifact and never scientific evidence.

Do not authenticate or run V2 benchmark inference merely because this proposal
exists. Freeze only after independent review of the implementation diff,
tests, qualification result, repository/environment checks, and exact ARC
commit.
