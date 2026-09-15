# V12 verification checklist

- [x] Branch from the exact V11 parent.
- [x] Add red/green provider-classification and ledger tests.
- [x] Add deterministic continuation, retry, interruption, recovery, and
  measurement-gate tests.
- [x] Record V11 closure outside the frozen V11 tree.
- [ ] Reconcile and freeze fresh V12 preregistration artifacts.
- [ ] Run post-freeze read-only preflight; do not execute `V12/a001`.
