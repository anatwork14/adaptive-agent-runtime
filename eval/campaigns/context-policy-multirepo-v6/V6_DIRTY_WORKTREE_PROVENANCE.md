# V6 Dirty Worktree Provenance

## Initial state

Before V6 work, `git rev-parse HEAD` was:

`7eaf3159bce5a479408a5f1df032eb1b883a9f83`

The worktree already contained one user modification in
`eval/studies/preregistration.py`. No staged changes existed. The exact
pre-existing source change was:

```diff
-        payload = plan.model_dump(mode="json")
+        payload = plan.model_dump(mode="json", exclude_unset=True)
```

This changed only the `PreregisteredStudy` branch of
`compute_plan_digest()`. It was present during every V6 qualification run.

## V6 changes

V6 retained that line and added the matching serialization change in
`save_preregistration()`:

```diff
-        json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
+        json.dumps(plan.model_dump(mode="json", exclude_unset=True), indent=2, sort_keys=True)
+        + "\n",
```

V6 also added the V6 campaign directory, the explicit-home subscription
environment policy in `adapters/codex.py`, and the associated qualification,
comparison, forecast, and review artifacts.

## Interpretation

The pre-existing and V6 serialization lines affect only deterministic
preregistration serialization/digest self-verification. They do not change
tasks, treatments, repositories, hidden-test content, statistics, budgets, or
provider/model identity. The matching save change is required for the
qualified V6 nested handoff: without it, a plan created with unset Pydantic
defaults fails after reload with a digest mismatch.

Because the pre-existing line was part of the qualified bytes and the matching
V6 save change repaired the observed serialization invariant, both are included
explicitly in the final V6 apparatus commit. No user work was silently reverted.

## Evidence

The pre-commit evidence directory contains the complete status, unstaged and
staged diffs, original HEAD, full `preregistration.py`, and its SHA-256:

`outputs/V6_DIRTY_STATE_BEFORE_COMMIT/`

At capture time the full `preregistration.py` SHA-256 was:

`50fa22caf4db10783a8b8f7c7490bc77f93cd43349a79d437300568d215e77b2`
