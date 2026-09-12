# ARC 0.16 Release Checklist

## Meta-preregistration
- [x] Repository selection is frozen before meta-analysis.
- [x] Meta plans contain exact per-repository study-plan digests.
- [x] Meta plans are self-digesting and tamper-evident.
- [x] Duplicate plan digests and duplicate benchmark IDs fail closed.
- [x] Provider/model/profile must match across repositories.
- [x] Baseline set and hard context/token/cost/gate protocol must match.
- [x] Repository-specific commit/task/hidden-test contracts may differ.

## Hierarchical inference
- [x] Repository is the outer statistical cluster.
- [x] Paired repetition remains the within-repository unit.
- [x] Task rows are never treated as independent cross-repository samples.
- [x] Bootstrap resamples repositories first and repetitions second.
- [x] Repository effects are equally weighted in the pooled point estimate.
- [x] Missing metric coverage remains explicit.
- [x] Repository-level resolved-rate W/T/L is retained.

## Input validation
- [x] Only preregistered completed studies are accepted.
- [x] Failed studies are rejected.
- [x] Exactly one completed study must match every frozen plan digest.
- [x] Missing, duplicate and unplanned repositories fail closed.
- [x] Provider/model/profile/benchmark/baseline drift fails closed.

## Outputs
- [x] `meta_study.json` preserves the aggregate contract.
- [x] Repository-effect CSV/JSONL is emitted.
- [x] Meta-effect CSV/JSONL is emitted.
- [x] Output manifest records file SHA-256 digests.

## CLI
- [x] `arc benchmark meta-preregister` freezes repository selection.
- [x] `arc benchmark meta` aggregates completed study artifacts offline.
- [x] Existing paired/repeated/preregister/run-plan/export commands remain unchanged.

## Validation
- [x] Synthetic tests cover plan tampering and protocol drift.
- [x] Synthetic tests cover hierarchical repository/repetition aggregation.
- [x] Synthetic tests cover frozen repository-selection rejection.
- [x] CLI registration and fail-fast argument validation are covered.
- [ ] Exact final branch head passes Python 3.11 CI.
- [ ] Exact final branch head passes Python 3.12 CI.
- [ ] Independent PR-triggered CI passes on the same frozen head.
- [ ] Squash merge is pinned to the validated head SHA.
- [ ] Post-merge main CI and Pages pass.

## Interpretation guardrail
- [x] Equal repository weighting is documented.
- [x] Metric direction is not conflated with utility.
- [x] Hierarchical CI is not presented as proof of external validity.
- [x] Real empirical claims still require authenticated provider-backed repository studies.
