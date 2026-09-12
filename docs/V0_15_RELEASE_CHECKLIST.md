# ARC 0.15 Release Checklist

## Preregistration integrity

- [x] Plans embed canonical validated manifests rather than mutable source paths.
- [x] One canonical repository commit is resolved and stored.
- [x] Plan payloads carry a SHA-256 digest and modified plans fail closed.
- [x] Unique baselines and complete pairwise comparison enumeration are enforced.
- [x] Repetition count, bootstrap samples, CI mass, analysis unit, primary metrics and exclusions are frozen.
- [x] Provider/profile/model/role/capabilities are frozen.
- [x] Visible test command, project budget and verification level are frozen.
- [x] Hidden tests are content-hashed without copying their contents into the plan.
- [x] Preregistration does not require provider login.

## Execution gate

- [x] `run-plan` requires provider readiness.
- [x] Repository base is re-resolved before execution.
- [x] Provider/model/profile fields are revalidated.
- [x] Visible tests and project budget are revalidated.
- [x] Hidden-test presence and digest are revalidated.
- [x] Frozen manifests are executed directly; external manifest files are not reread.
- [x] Attempt identity is explicit and retained in provenance.
- [x] Plan digest and predeclared exclusions are copied into study provenance.
- [x] Existing repeated-study artifact collision protection prevents silent overwrite.

## Tidy exports

- [x] Export works offline from persisted study artifacts.
- [x] Task-level CSV and JSONL are emitted.
- [x] Repetition-level CSV and JSONL are emitted.
- [x] Pair/metric-level CSV and JSONL are emitted.
- [x] Execution order and order position are retained.
- [x] Export manifest records row counts and file SHA-256 digests.
- [x] Preregistered plan digest is propagated when available.

## Operator surface

- [x] `arc benchmark preregister` creates a frozen study plan.
- [x] Existing preregistration output paths are rejected by the CLI.
- [x] `arc benchmark run-plan` executes a frozen plan.
- [x] `arc benchmark export` produces offline tidy tables.
- [x] Existing `paired` and `repeated` commands remain unchanged.

## Validation

- [x] Unit tests cover plan digest tampering.
- [x] Unit tests cover hidden-test/config drift rejection.
- [x] Unit tests cover offline tidy export and file digests.
- [x] CLI help tests cover the new surfaces.
- [x] End-to-end mock smoke test covers preregister -> run-plan -> export.
- [x] Smoke test verifies the source repository HEAD is unchanged.
- [ ] Exact final branch head passes Python 3.11 CI.
- [ ] Exact final branch head passes Python 3.12 CI.
- [ ] Independent PR-triggered CI passes on the same frozen head.
- [ ] Squash merge is pinned to the validated head SHA.
- [ ] Post-merge main CI and Pages pass.

## Interpretation guardrail

- [x] Documentation states that plan integrity cannot fingerprint opaque provider backend revisions.
- [x] Mock executions are described as apparatus validation only.
- [x] Real empirical claims remain dependent on authenticated provider-backed repetitions and retained attempt history.
