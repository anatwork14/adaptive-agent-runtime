# ARC 0.15 — Pre-registered Provider Studies

ARC 0.15 turns the repeated paired benchmark harness into an execution workflow that can be frozen before a real provider-backed study begins.

## Why preregistration exists

ARC 0.14 already isolates B3/B5/B7 trajectories and bootstraps repetition-level paired deltas. The remaining validity risk is changing the study after observing partial outcomes: editing manifests, switching models, changing hidden tests, changing budgets, adding/removing exclusions, or altering the number of repetitions.

A preregistered plan freezes those choices into one self-digesting JSON artifact before execution.

## Frozen plan contents

`arc benchmark preregister` embeds the complete validated manifests rather than only storing file paths. It also records:

- canonical Git commit resolved from every manifest;
- study ID and benchmark ID;
- agent profile, provider and declared model;
- profile role/capabilities;
- visible test command;
- project USD ceiling;
- verification level;
- hidden-test tree SHA-256 digest when hidden tests are used;
- repetition count;
- bootstrap sample count and CI mass;
- balanced crossover schedule identifier;
- paired-repetition analysis unit;
- primary metrics;
- every baseline comparison;
- predeclared exclusion rules;
- UTC creation timestamp.

The plan receives a SHA-256 `plan_digest` over the canonical JSON payload with the digest field blanked. Loading a modified plan fails closed.

## Hidden-test integrity

ARC does not copy hidden-test contents into the plan. Instead it recursively hashes sorted relative paths and file bytes. `run-plan` recomputes that digest before execution. Adding, deleting, renaming or editing a hidden-test file changes the digest and blocks the run.

This protects the correctness contract while keeping hidden test contents external to benchmark artifacts.

## Provider readiness

Preregistration does **not** require a live provider login. This allows a study design to be frozen before credentials or execution machines are available.

Execution does require the configured profile to pass ARC's provider doctor check. `run-plan` then revalidates provider, model, role/capabilities, visible tests, project budget, verification level, hidden-test presence/digest, and the canonical repository base.

## CLI

Create a plan:

```bash
arc benchmark preregister \
  b3.yaml b5.yaml b7.yaml \
  --repo . \
  --study-id repo-study-01 \
  --output prereg/repo-study-01.json \
  --repeats 6 \
  --bootstrap-samples 2000 \
  --ci 0.95 \
  --hidden-test-dir /secure/hidden-tests \
  --exclude "provider outage before first task"
```

Execute the frozen plan later on the authenticated machine:

```bash
arc benchmark run-plan prereg/repo-study-01.json \
  --repo . \
  --attempt-id a001 \
  --hidden-test-dir /secure/hidden-tests
```

Attempts are intentionally explicit. A retry must use a new attempt ID such as `a002`; the repeated-study runner already refuses to overwrite an existing study artifact directory. All attempts therefore remain auditable instead of silently replacing failed or inconvenient outcomes.

## Tidy offline export

After a study completes:

```bash
arc benchmark export /path/to/study
```

ARC writes deterministic offline exports under `<study>/exports` by default:

```text
tasks.csv
tasks.jsonl
repetitions.csv
repetitions.jsonl
pairs.csv
pairs.jsonl
export_manifest.json
```

`tasks` contains one row per measured task/treatment/repetition. `repetitions` contains one row per baseline summary in each repetition. `pairs` contains one row per aggregate metric for each baseline pair. Arrays/dictionaries are JSON encoded inside CSV cells.

`export_manifest.json` records row counts, source study identity, preregistered plan digest when available, and SHA-256 hashes for every exported table. Export never opens the live ARC database or source repository.

## Evidence discipline

The plan digest is not a claim that an opaque provider backend is immutable. Provider-side model revisions that are not exposed by the provider remain an external limitation and should be reported.

A preregistered mock study validates the workflow only. Empirical claims still require authenticated provider-backed runs, sufficient repetitions, retained traces/artifacts, coverage reporting, and honest accounting of every failed or excluded attempt.
