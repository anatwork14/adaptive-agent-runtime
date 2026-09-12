# V2 Target Environment Qualification

Status: qualified for proposed V2 review; this document does not freeze V2.

All qualification work used disposable copies outside the canonical benchmark
clones. The canonical clones under `/Users/teobun/arc-study/repos/` remained
clean and at their frozen commits. No provider inference or benchmark task was
run.

## Source identities

| Repository | Frozen commit |
| --- | --- |
| Click | `6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1` |
| HTTPX | `b5addb64f0161ff6bfe94c124ef76f6a1fba5254` |
| python-dotenv | `a00cb2eed0704cd6d2071b2004c37e95ccc86ee5` |

## Actual qualified gate harnesses

The `IntegrationGate.evaluate_submission()` path was exercised for each
repository. Each qualification created a candidate commit from the frozen
base, allowed the gate to create its temporary worktree and cherry-pick that
commit, then observed `G1_static`, `G2_visible_tests`, and final integration.
The candidate commit also contained a qualification-only import test under the
repository's normal test tree; the test asserted that the imported module's
`__file__` was below the gate worktree.

| Repository | Backend / image identity | Python/toolchain | Command | Result |
| --- | --- | --- | --- | --- |
| Click | Docker `arc-v2-click:qualified@sha256:7fae74105025e759c4244de903b1385271df9ac4f8e4bfb3d1589094d2ec92a4` | CPython 3.10.7; uv-locked dev/tests environment | `python -m pytest -q` | 2059 passed, 24 skipped, 31000 deselected, 1 xfailed |
| HTTPX | Docker `arc-v2-httpx:qualified@sha256:1f8b4320b6d1b4ab22121442732f3f684e1fe77162de563beb841b0dc340d8cf` | CPython 3.11.16; declared requirements editable environment | `python -m pytest -q -W ignore::ResourceWarning -m "not network"` | 1413 passed, 1 skipped, 5 deselected |
| python-dotenv | Docker `arc-v2-python-dotenv:qualified@sha256:d7e1c1d915ad92a48fe0d915b9f951bd70af3bab5737d03f83d31281d84dc32b` | CPython 3.10.7; declared requirements editable environment | `python -m pytest -q` | 255 passed, 31 warnings |

The HTTPX `network` marker is excluded because the sandbox uses `--network
none`; the exclusion is explicit in the frozen command. Click's harness
explicitly permits executable files in its `/tmp` tmpfs because its test suite
tests shell-script pager fixtures. The backend remains read-only at the root,
drops all capabilities, disables privilege escalation, limits CPU/memory/PIDs,
and forwards only the recorded non-secret environment.

## Hidden grader boundary

The same Docker runner supports a separate hidden-test invocation. The
candidate workspace is mounted at `/workspace`; the hidden repository-specific
directory is mounted at `/arc-hidden-tests` read-only; the provider process is
never involved in this invocation and never receives that mount. Hidden pytest
cache creation is disabled because the hidden mount is read-only.

A synthetic external fixture was run through this exact backend: the passing
candidate passed and the intentionally failing candidate failed. The hidden
fixture remained external to both candidates, its candidate module was
imported from `/workspace`, and no hidden mount mutation was possible. The
canonical freezer remains the only code that validates the three campaign
hidden-tree digests.

## Contract consequence

V2 stores each command, Docker image name and immutable local image ID, backend,
non-secret environment, hidden command/environment, Python/toolchain identity,
timeout, and qualification ID in the self-digesting repository runtime
contract. The preflight compares the live configuration with that exact
harness. B3, B5, and B7 use the same repository harness without treatment
specific variation.
