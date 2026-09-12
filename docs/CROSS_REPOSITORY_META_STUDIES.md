# ARC 0.16 — Cross-Repository Meta-Studies

ARC 0.16 moves the experimental unit one level higher. A preregistered repeated study on one repository is useful evidence, but it can still overfit repository-specific structure. Cross-repository claims therefore require repository-clustered analysis rather than pooling task rows or repetitions across repositories.

## Statistical hierarchy

ARC keeps the existing hierarchy intact:

```text
repository
  └─ paired repetition
       └─ ordered task sequence
```

For each repository and baseline pair, ARC first computes one delta per paired repetition. The repository is then summarized by the mean of those repetition-level deltas.

The cross-repository bootstrap resamples repositories first. For every selected repository it then resamples that repository's paired repetition deltas and computes a repository mean. The bootstrap statistic is the equal-weight mean of the selected repository means.

This avoids treating correlated tasks or repetitions from the same codebase as independent observations.

## Repository selection is preregistered

Repository selection is itself an analysis decision. ARC 0.16 therefore adds a self-digesting meta-study plan that freezes the exact per-repository preregistration plan digests before completed results are aggregated.

```bash
arc benchmark meta-preregister \
  prereg/repo-a.json \
  prereg/repo-b.json \
  prereg/repo-c.json \
  --meta-id context-policy-multirepo-v1 \
  --output prereg/meta-v1.json \
  --bootstrap-samples 5000 \
  --ci 0.95 \
  --seed 42
```

The meta-plan requires the repositories to use the same provider, model, agent profile, baseline set, hard context-token ceiling, per-task USD ceiling, project USD ceiling, verification level, and repetition count. Repository commits, tasks, hidden tests, benchmark IDs, and plan digests are expected to differ.

The plan has its own SHA-256 digest. Modified plans fail closed.

## Aggregating completed studies

After each repository has been executed through `arc benchmark run-plan`, aggregate the completed attempt directories:

```bash
arc benchmark meta \
  prereg/meta-v1.json \
  /results/repo-a-study-a001 \
  /results/repo-b-study-a001 \
  /results/repo-c-study-a001 \
  --output-dir results/meta-v1
```

ARC accepts exactly one completed study per frozen repository plan digest. Missing, duplicate, unplanned, failed, or non-preregistered study artifacts are rejected.

The completed study must still match the frozen provider, model, agent profile, benchmark ID, and baseline set.

## Metrics

The same primary metrics frozen by ARC 0.15 are aggregated:

- resolved rate;
- mean delivered context tokens;
- mean observed provider tokens;
- mean observed cost;
- p95 end-to-end latency;
- stale-delivery rate.

Missing telemetry stays missing. A repository contributes to one metric only when it has at least one paired repetition with observations on both sides.

Each hierarchical result reports:

- repository count with paired coverage;
- total paired repetitions contributing;
- equal-weight mean repository effect;
- median repository effect;
- hierarchical bootstrap confidence interval.

Repository W/T/L is descriptive and uses each repository's mean resolved-rate delta.

## Artifacts

The output directory contains:

```text
meta_study.json
repository_effects.csv
repository_effects.jsonl
meta_effects.csv
meta_effects.jsonl
meta_export_manifest.json
```

`repository_effects` preserves each repository's mean effect. `meta_effects` contains one row per baseline pair and metric. The export manifest records SHA-256 digests for the produced files.

## Interpretation

A positive delta means baseline A > baseline B for the named orientation. That does not automatically mean "better" for cost, latency, or context-size metrics; interpret each metric according to its direction.

ARC deliberately gives each repository equal weight in the cross-repository point estimate. A large repository with many tasks or repetitions therefore cannot dominate simply because it generated more rows.

The hierarchical bootstrap quantifies sampling uncertainty under the observed repository/repetition design. It does not solve every external-validity problem, does not fingerprint opaque provider backend revisions, and is not a substitute for inspecting repository-specific effects.

## Evidence discipline

For a paper-level claim:

1. preregister each repository study before execution;
2. preregister the repository set before inspecting cross-repository outcomes;
3. execute every repository with the same provider/model/budget/gate protocol;
4. retain every explicit attempt;
5. apply only predeclared exclusions;
6. report repository-level effects alongside the pooled hierarchical interval;
7. explain missing telemetry and failed/rejected candidates;
8. avoid task-row or repetition-row pseudoreplication.

The next empirical step is to choose and freeze a small, diverse repository suite, then execute the authenticated provider-backed studies on the server.
