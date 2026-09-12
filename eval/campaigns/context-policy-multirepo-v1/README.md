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
- reasoning effort: `high`, pinned in the effective CLI argv
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
- visible test command: `python -m pytest -q -m "not network"`
- grading network: disabled
- grading Python path: `/workspace/src:/workspace`
- no injected faults in the primary study

The machine-readable source of truth is `campaign_contract.json`. The canonical Codex command override is intentionally public because it contains no credential. Authentication values are never stored in the campaign contract or runtime lock.

## Why these are sequences rather than independent tasks

Each repository contains three ordered maintenance tasks. T002 depends on T001 and T003 depends on T002. Later work intentionally reuses an abstraction or policy introduced earlier. This makes context continuity scientifically relevant instead of turning the benchmark into a collection of unrelated one-shot patches.

### Treatment separation

Successful subprocess coding-agent runs primarily contribute durable `TASK_SUMMARY` episodic memory. In a three-task sequence, a fixed B5 `top_k=5` policy can therefore retain essentially all prior successful summaries. Without an additional provenance rule, B7's lexical/vector fallback could retrieve the same small history and collapse the B5-vs-B7 treatment contrast.

The frozen B7 treatment is therefore dependency-aware for episodic history: when a task declares dependencies, `TASK_SUMMARY` and `EPISODE` memories from declared predecessor tasks remain eligible through dependency-linked retrieval, while unrelated episodic history is excluded from generic lexical/vector expansion. Root tasks with no declared dependencies retain generic semantic episode fallback, and non-episodic memory classes retain their existing retrieval behavior.

B5 remains the unchanged naive vector top-k baseline. For example, T003 may receive T001 and T002 summaries under B5, whereas B7 scopes successful episodic history to its declared predecessor T002. This treatment distinction is frozen before any provider execution; it is not selected after observing benchmark outcomes.

### Click

1. Add opt-in sensitive metadata to parameters without changing normal parsing/help behavior.
2. Build a structured `Context.parameter_snapshot()` that records values and `ParameterSource` while redacting sensitive values.
3. Generalize the sensitive contract cleanly across options and arguments without duplicating behavior.

### HTTPX

1. Introduce `Headers.redacted()` as a reusable, non-mutating sensitive-header redaction primitive.
2. Route verbose request-header rendering through that policy with explicit `--show-sensitive` opt-out.
3. Apply the exact same policy to verbose response headers while preserving formatting and duplicate ordering.

### python-dotenv

1. Preserve source-line provenance as public immutable `DotEnvEntry` data.
2. Add `dotenv_values_with_metadata(...)` with interpolated values and winning source lines.
3. Surface the same provenance through `dotenv list --format json-meta` without changing existing formats.

## Grading environment is part of the treatment contract

Click and python-dotenv use `src/` layouts. Running `python -m pytest` from the repository root without controlling imports can therefore test an unrelated package from `site-packages` instead of the candidate commit. The original generic ARC sandbox also contained ARC dependencies rather than the exact dependency surface needed by all three target repositories.

The primary campaign fixes that construct-validity problem explicitly:

- visible and hidden grading both run in Docker;
- candidate source is forced ahead of site-packages using `PYTHONPATH=/workspace/src:/workspace`;
- hidden tests remain outside the repository and are mounted read-only only after provider work finishes;
- the sandbox has network disabled;
- HTTPX tests explicitly marked `network` are excluded because the grading sandbox intentionally has no network;
- `Dockerfile.grading` provides the common dependency surface needed by the three pinned repositories;
- the runtime lock freezes the resulting Docker image ID, not merely a mutable image tag;
- freeze performs an import-path probe plus the complete visible test command on each untouched pinned base before emitting any preregistration.

A base repository that imports from `/usr/.../site-packages`, lacks a dependency, times out, or fails its visible suite makes the campaign freeze fail. Such a failure is an environment problem, not an agent outcome.

## Hidden grading

Actual hidden tests MUST remain outside this public repository. Their public behavior contracts are documented in `hidden_test_contracts.md`. The private suites are hashed independently per repository; the expected tree digests are frozen in `campaign_contract.json`.

Any edit, rename, add, or delete in a private hidden suite after freeze invalidates the study. Do not preregister against an empty or placeholder hidden directory.

## Runtime reproducibility lock

`runtime_lock.py` is separate from ARC's historical v0.16 preregistration schema so old plan digests remain valid. For this campaign it freezes and later verifies:

- profile, provider, model, role and capabilities;
- SHA-256 of the effective provider argv, including reasoning configuration;
- allowed environment-variable names;
- installed provider CLI version;
- grading sandbox image tag and immutable Docker image ID;
- Docker CLI version;
- ARC repository commit;
- a clean ARC evaluation-engine worktree at both freeze and execution time.

The raw effective provider argv is not written to the runtime lock. A dirty ARC checkout fails closed even if `HEAD` still equals the frozen commit, because uncommitted code would change the benchmark engine without changing its SHA. Rebuilding or retagging the grading image after freeze also fails closed if its image ID changes.

## Build the campaign grading image

Build the grading image from the same clean ARC commit that will freeze and execute the study:

```bash
docker build \
  -f eval/campaigns/context-policy-multirepo-v1/Dockerfile.grading \
  -t arc-context-policy-v1:py311 \
  .

docker image inspect arc-context-policy-v1:py311 --format '{{.Id}}'
```

Do this **before** `freeze_campaign.py`. You do not need to set `ARC_SANDBOX_IMAGE` manually: the campaign runtime lock resolves the canonical image name from `campaign_contract.json` and exports it into the current process when needed.

Do not rebuild or retag this image between freeze and provider execution. If the image must change, create a new campaign/version and freeze again before observing provider outcomes.

## One-command freeze before any provider run

Prepare three clean clones at the exact commits above and extract the private hidden-test bundle so the hidden root contains `click/`, `httpx/`, and `python-dotenv/`. Install the intended Codex CLI build and build the grading image above, but provider login is not required yet. The ARC repository itself must also be clean and checked out at the version that will execute the study.

Then run:

```bash
python eval/campaigns/context-policy-multirepo-v1/freeze_campaign.py \
  --click-repo /study/repos/click \
  --httpx-repo /study/repos/httpx \
  --python-dotenv-repo /study/repos/python-dotenv \
  --hidden-root /secure/hidden/context-policy-multirepo-v1-hidden \
  --output-dir /secure/prereg/context-policy-multirepo-v1
```

Before emitting any repository plan, the command now performs the following pre-treatment checks:

1. exact public repository HEADs and clean source worktrees;
2. exact private hidden-tree digests;
3. provider command and CLI version;
4. exact Docker grading image ID;
5. clean ARC engine and exact ARC commit;
6. detached untouched-base import probes proving `click`, `httpx`, and `dotenv` resolve from `/workspace` candidate source;
7. the exact visible test command on every untouched pinned base inside the frozen network-disabled image.

It then deterministically configures the same ARC `builder` profile in all three clones and emits:

```text
runtime-lock.json
click-context-policy-v1.json
httpx-context-policy-v1.json
python-dotenv-context-policy-v1.json
context-policy-multirepo-v1.json
freeze-manifest.json
```

The three repository plans freeze V1 explicitly. The final meta plan freezes the exact three repository-plan digests before provider execution. `freeze-manifest.json` records the ARC commit, runtime-lock digest, provider CLI version, grading image tag/ID, Docker CLI version, untouched-base health reports, repository plan digests, meta-plan digest, and `provider_execution_started=false`.

Do not edit any generated freeze artifact. If anything in the execution contract must change, create a new campaign/version rather than overwriting this one.

## Authenticated execution gate

Only after the complete freeze directory exists should provider authentication and expensive execution begin. Authenticate through the vendor CLI and confirm it independently:

```bash
codex login
codex login status
```

The campaign does **not** rely on generic ARC `doctor_profile()` readiness here. The `builder` profile intentionally uses a command override to pin reasoning effort, and generic override readiness does not prove that the Codex account is signed in. `execute_campaign.py` calls the vendor authentication probe directly.

Keep benchmark results and disposable workspaces outside ARC and all three target repositories. First run the read-only preflight:

```bash
python eval/campaigns/context-policy-multirepo-v1/execute_campaign.py \
  --click-repo /study/repos/click \
  --httpx-repo /study/repos/httpx \
  --python-dotenv-repo /study/repos/python-dotenv \
  --hidden-root /secure/hidden/context-policy-multirepo-v1-hidden \
  --freeze-dir /secure/prereg/context-policy-multirepo-v1 \
  --results-root /study/results \
  --workspace-root /study/runtime \
  --attempt-id a001
```

A successful preflight revalidates, immediately before inference:

- all self-digesting repository plans and the meta plan;
- runtime-lock digest, effective provider argv, CLI version and ARC commit;
- the exact grading Docker image ID and Docker CLI version;
- clean ARC and target-repository worktrees;
- exact pinned target `HEAD`s;
- private hidden-test tree digests;
- live ARC profile/test/budget/verification settings against every preregistration;
- direct Codex authentication status;
- fresh result/workspace destinations outside every source repository.

The command is read-only without `--execute`. If authentication is missing it still reports the structural checks but exits non-zero with `ready_for_execution=false`.

After reviewing that output, start the primary provider attempt by adding exactly one flag:

```bash
python eval/campaigns/context-policy-multirepo-v1/execute_campaign.py \
  --click-repo /study/repos/click \
  --httpx-repo /study/repos/httpx \
  --python-dotenv-repo /study/repos/python-dotenv \
  --hidden-root /secure/hidden/context-policy-multirepo-v1-hidden \
  --freeze-dir /secure/prereg/context-policy-multirepo-v1 \
  --results-root /study/results \
  --workspace-root /study/runtime \
  --attempt-id a001 \
  --execute
```

The execution driver runs repositories in the frozen campaign order `click -> httpx -> python-dotenv`. For every repository it invokes the public `arc benchmark run-plan` path, writes a persistent command log, verifies the emitted provenance plan digest, and runs the deterministic tidy export. Only after all three repository studies succeed does it invoke the frozen hierarchical meta-analysis.

The campaign attempt writes an atomic `execution-manifest.json` containing the freeze digest, runtime-lock digest, ARC commit, provider CLI version, repository plan digests, exact study/export locations, timestamps, per-repository states, meta-analysis state, and whether provider execution started.

## Failure and retry discipline

There is deliberately no automatic retry, resume, overwrite, or "pick the best attempt" behavior.

- A failed campaign attempt remains on disk with `status=FAILED`.
- A new provider attempt requires a new explicit attempt ID.
- The current preregistered exclusions are only `provider outage before the first provider turn` and `host failure before the first provider turn`. A later failure is **not** automatically eligible for exclusion/replacement.
- If provider execution itself completed but only the offline export or meta-analysis failed, do **not** rerun the provider. Repair or rerun the offline operation against the already-persisted study artifacts.
- Retain every failed attempt tree and execution log for the thesis audit trail.

This strict policy prevents an operator from silently replacing a weak or inconvenient stochastic result.

## Manual preregistration fallback

If the campaign driver cannot be used, the CLI requires the study's declared verification level and test command to be explicit in the configured repository:

```bash
arc benchmark preregister \
  b3.yaml b5.yaml b7.yaml \
  --repo . \
  --study-id <repo>-context-policy-v1 \
  --output <repo>-context-policy-v1.json \
  --verification-level V1 \
  --repeats 6 \
  --bootstrap-samples 2000 \
  --ci 0.95 \
  --hidden-test-dir /secure/hidden/<repo> \
  --exclude "provider outage before the first provider turn" \
  --exclude "host failure before the first provider turn"
```

The one-command freeze and execution drivers are preferred because they remove operator drift across repositories and also freeze the grading image.

## Interpretation discipline

The repository is the top-level analysis cluster. Never pool task rows across repositories. Primary claims come from the preregistered hierarchical meta-analysis. Repository-specific task outcomes are diagnostic secondary analyses. Provider-side model revisions that the provider does not expose remain an external reproducibility limitation and must be reported.
