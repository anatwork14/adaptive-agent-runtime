# Context Policy Multi-Repository Study v1

This directory freezes the public portion of ARC's first real provider-backed cross-repository study. It evaluates whether B7's adaptive context policy improves long-horizon coding work relative to B3 static structured context and B5 fixed vector top-k retrieval under matched budgets.

## Frozen repository bases

| Repository | Domain | Commit |
|---|---|---|
| pallets/click | CLI framework | `6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1` |
| encode/httpx | HTTP / async client | `b5addb64f0161ff6bfe94c124ef76f6a1fba5254` |
| theskumar/python-dotenv | configuration / parsing | `a00cb2eed0704cd6d2071b2004c37e95ccc86ee5` |

Never replace these SHAs with moving branch names.

## Shared protocol

The primary study uses one provider/model/profile across all repositories:

- provider: `codex`
- model: `gpt-5.3-codex`
- agent profile: `builder`
- baselines: `B3`, `B5`, `B7`
- context ceiling: 12,000 tokens per task
- hard task ceiling: USD 2.00
- hard project ceiling: USD 350.00
- repetitions: 6
- repository bootstrap samples: 2,000
- repository CI mass: 0.95
- meta bootstrap samples: 5,000
- meta CI mass: 0.95
- meta random seed: 42
- verification level: V1
- visible test command: `python -m pytest -q`
- no injected faults in the primary study

The operator must configure the same effective Codex command in every target clone. The intended command is Codex with model `gpt-5.3-codex` and high reasoning. Before any preregistration, run `runtime_lock.py freeze` once and `runtime_lock.py verify` in every repository. The lock stores only a SHA-256 digest of the effective argv, never the argv itself.

## Why these are sequences rather than independent tasks

Each repository contains three ordered maintenance tasks. T002 depends on T001 and T003 depends on T002. Later work intentionally reuses an abstraction or policy introduced earlier. This makes context continuity scientifically relevant instead of turning the benchmark into a collection of unrelated one-shot patches.

### Click

1. Add opt-in sensitive metadata to parameters without changing normal parsing/help behavior.
2. Build a structured `Context.parameter_snapshot()` that records values and `ParameterSource` while redacting sensitive values.
3. Generalize the sensitive contract cleanly across options and arguments without duplicating behavior.

### HTTPX

1. Introduce a reusable, non-mutating sensitive-header redaction primitive.
2. Route verbose request-header rendering through that policy with an explicit unsafe opt-out.
3. Apply the exact same policy to verbose response headers while preserving formatting and duplicate ordering.

### python-dotenv

1. Preserve source-line provenance as a public immutable entry representation.
2. Add an interpolated metadata-returning API that keeps the winning source line for duplicate keys.
3. Surface the same provenance through a new CLI JSON metadata format without changing existing formats.

## Hidden grading

Actual hidden tests MUST remain outside this public repository. Their public behavior contracts are documented in `hidden_test_contracts.md`. Before preregistration, place the private suites in one external directory per repository. ARC hashes the complete hidden tree into the repository study plan. Any edit, rename, add, or delete after preregistration must invalidate execution.

Do not preregister against an empty or placeholder hidden directory.

## Operator sequence

For each target repository clone:

```bash
git checkout --detach <FROZEN_SHA>
arc init . --project-id context-policy-multirepo-v1
# Configure profile `builder` as Codex / gpt-5.3-codex and set project ceiling to 350 USD.
python /path/to/adaptive-agent-runtime/eval/campaigns/context-policy-multirepo-v1/runtime_lock.py verify \
  --repo . --lock /secure/context-policy-runtime-lock-v1.json

arc benchmark preregister \
  /path/to/<repo>/b3.yaml /path/to/<repo>/b5.yaml /path/to/<repo>/b7.yaml \
  --repo . \
  --study-id <repo>-context-policy-v1 \
  --output /secure/prereg/<repo>-context-policy-v1.json \
  --repeats 6 --bootstrap-samples 2000 --ci 0.95 \
  --hidden-test-dir /secure/hidden/<repo> \
  --exclude "provider outage before the first provider turn" \
  --exclude "host failure before the first provider turn"
```

After all three repository plans exist, freeze the repository set before executing any treatment:

```bash
arc benchmark meta-preregister \
  /secure/prereg/click-context-policy-v1.json \
  /secure/prereg/httpx-context-policy-v1.json \
  /secure/prereg/python-dotenv-context-policy-v1.json \
  --meta-id context-policy-multirepo-v1 \
  --output /secure/prereg/context-policy-multirepo-v1.json \
  --bootstrap-samples 5000 --ci 0.95 --random-seed 42
```

Only after the meta plan is frozen should authenticated provider execution begin. Retain every attempt ID, including failed attempts.

## Interpretation discipline

The repository is the top-level analysis cluster. Never pool task rows across repositories. Primary claims come from the preregistered hierarchical meta-analysis. Repository-specific task outcomes are diagnostic secondary analyses. Provider-side alias revisions that the provider does not expose remain an external reproducibility limitation and must be reported.