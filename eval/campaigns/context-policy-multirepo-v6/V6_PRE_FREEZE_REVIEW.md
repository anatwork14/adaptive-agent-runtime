# ARC V6 Pre-Freeze Review

## Scope boundary

This is an apparatus review package only. The V6 canonical freeze was not run,
no benchmark provider execution occurred, and V6/a001 was not created.

V6 uses ChatGPT subscription-backed Codex authentication through the existing
V4 home. The abandoned `codex-v6-api-home` is not used. No API-key workflow is
part of this campaign.

## Results

| Check | Result |
|---|---|
| V5→V6 normalized scientific contract | PASS |
| All nine V5→V6 manifest comparisons | PASS |
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

ARC has a pre-existing user modification in `eval/studies/preregistration.py`.
It was preserved. V6 additionally hardens saved preregistration serialization
to keep plan digests self-verifying and narrows explicit-home Codex child
processes to the subscription-home environment policy. Because the worktree is
not clean, no V6 runtime lock or canonical freeze was created.

## Required final state

`benchmark_provider_execution=false`, `V6 canonical freeze=NOT RUN`, and
`V6/a001=NOT RUN`.
