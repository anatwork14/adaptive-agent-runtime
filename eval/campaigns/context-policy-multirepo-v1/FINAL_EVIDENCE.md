# Final evidence closure

This is the last step of `context-policy-multirepo-v1`. It is intentionally **offline** and must not start, resume, or repeat provider inference.

## Required state

Run this only after `execute_campaign.py --execute` completed successfully and the attempt contains:

```text
execution-manifest.json                  status=SUCCEEDED
repositories/click/...                   completed study + exports
repositories/httpx/...                   completed study + exports
repositories/python-dotenv/...           completed study + exports
meta/meta_study.json
meta/meta_export_manifest.json
```

A failed provider attempt is not finalizable. Do not repair a failed provider attempt by selecting only successful repetitions or repositories.

## Finalize

For a successful primary attempt such as:

```text
/study/results/context-policy-multirepo-v1/a001
```

run:

```bash
python eval/campaigns/context-policy-multirepo-v1/finalize_campaign.py \
  /study/results/context-policy-multirepo-v1/a001
```

The finalizer performs no provider checks and no provider calls. It verifies:

- `execution-manifest.json` belongs to this campaign and is `SUCCEEDED`;
- all three repository studies are successful;
- study provenance carries the exact preregistered plan digest;
- every repository tidy-export file matches `export_manifest.json` SHA-256;
- the meta-analysis is successful;
- every hierarchical meta file matches `meta_export_manifest.json` SHA-256;
- the exact repository-plan set entering the meta-analysis matches the execution manifest;
- every consumed artifact path remains inside the campaign attempt tree.

It then creates:

```text
final-evidence/
├── final_report.md
├── claim_summary.json
└── evidence-manifest.json
```

## `final_report.md`

The report presents the frozen meta-analysis in a thesis-readable form. B7 comparisons are re-oriented only for readability as:

```text
B7 - comparator
```

This **does not** recompute or change the preregistered analysis. If the frozen result is stored as `B3 - B7`, the finalizer only multiplies the point estimate and interval by `-1` while reversing interval bounds.

Metric direction is fixed before interpretation:

- higher is better: `resolved_rate`;
- lower is better: `mean_context_tokens`, `mean_provider_tokens`, `mean_cost_usd`, `p95_end_to_end_latency_ms`, `stale_delivery_rate`.

The report labels an effect as:

- `direction favors B7` only when the frozen hierarchical interval excludes zero in the B7-favorable direction;
- `direction favors comparator` only when it excludes zero in the opposite direction;
- `uncertain CI includes zero` when zero remains inside the frozen interval;
- `unobserved` when the metric was not observed consistently enough to produce an effect.

These are descriptive evidence labels, not universal significance claims.

## `claim_summary.json`

This is the machine-readable counterpart to the report. It contains the exact B7-oriented point estimates, interval bounds, repository/repetition counts, preferred metric direction, and evidence label.

Use this file for figures/tables instead of manually transcribing numbers from terminal output.

## `evidence-manifest.json`

This is the audit closure artifact. It records SHA-256 hashes for:

- the execution manifest;
- each repository `study.json`, `provenance.json`, and `aggregates.json`;
- all verified repository tidy-export files and their export manifests;
- all hierarchical meta-export files and the meta export manifest;
- `final_report.md` and `claim_summary.json`.

The evidence manifest is itself self-digesting through `manifest_digest`.

## Statistical discipline after finalization

The frozen hierarchy remains:

```text
repository
  └─ paired repetition
       └─ ordered task sequence
```

Therefore:

- do not pool task rows as independent observations;
- do not choose the best repetition or best repository;
- do not replace the hierarchical confidence interval with a task-level test;
- do not silently convert missing provider-token/cost observations to zero;
- repository/task analyses remain diagnostic unless preregistered as primary;
- report provider-side model-alias opacity as an external reproducibility limitation.

Once `final-evidence/` exists and its manifest is archived with the raw attempt tree and frozen preregistration directory, the empirical pipeline is complete. Further method changes belong to a new campaign/version rather than a rewrite of this one.
