# V9 implementation plan

1. Record the V8 closure externally as immutable historical evidence.
2. Copy only the V8 scientific campaign inputs into a new V9 campaign namespace;
   do not copy V8 results or raw evidence.
3. Implement and test the append-only SQLite task ledger and the explicit
   provider-censor/retry/scoring policy.
4. Add deterministic provider-free regressions and rerun the existing ARC and
   Docker qualification suites without provider inference.
5. Freeze V9 once, verify the generated self-digests and parity, then run the
   read-only preflight. Do not start `V9/a001`.

## Acceptance gates

- V8 closure report contains the required status and preserved digest pointers.
- The V9 contract declares no scientific change and all operational rules before
  freeze.
- Ledger transitions are transactional, append-only, and resume from persisted
  state rather than filesystem existence.
- All provider-free regressions and Docker/hidden/network/timeout checks pass.
- V9 preregistration, plan/meta/lock digests, and read-only preflight pass.
