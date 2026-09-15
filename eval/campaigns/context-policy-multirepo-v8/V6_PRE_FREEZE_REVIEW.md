# ARC V8 Pre-Freeze Review

## Scope boundary

This is an apparatus review package only. The V8 canonical freeze was not run,
no benchmark provider execution occurred, and V8/a001 was not created.

V8 uses ChatGPT subscription-backed Codex authentication through the existing
V4 home. The abandoned `codex-v8-api-home` is not used. No API-key workflow is
part of this campaign.

## Results

| Check | Result |
|---|---|
| V5→V8 normalized scientific contract | PASS |
| All nine V5→V8 manifest comparisons | PASS |
| Treatment/model/timeout/harness equality | PASS |
| ChatGPT authentication and config stability | PASS |
| Non-benchmark provider qualification | PASS |
| Nested provider-environment handoff | PASS |
| Synthetic success/timeout E2E | PASS |
| Full ARC suite | PASS: 212 passed, 2 warnings |
| Docker image identities | PASS: all three exact digests |
| Docker visible harnesses | PASS: all three |
| Docker clean-base hidden harnesses | LIMITATION: all three fail on unmodified base repositories |

The Docker hidden result is not treated as a scientific result and hidden tests
were not inspected or modified. The provider-free synthetic hidden grader
success path passes, so the controlled grader boundary is exercised. The
clean-base hidden result is retained as evidence that the actual task graders
require candidate changes before they can pass.

## Git state

The pre-qualification dirty-state evidence records a pre-existing user
modification in `eval/studies/preregistration.py`; it was preserved rather than
silently reverted. V8 additionally hardens saved preregistration serialization
to keep plan digests self-verifying and narrows explicit-home Codex child
processes to the subscription-home environment policy. Those intended changes
are now committed in the final apparatus commit, and the ARC worktree is clean.
The final apparatus commit is recorded in the external review evidence; no V8
runtime lock or canonical freeze was created.

## Required final state

`benchmark_provider_execution=false`, `V8 canonical freeze=NOT RUN`, and
`V8/a001=NOT RUN`.
