# ARC 0.17.0

ARC 0.17.0 is a software/apparatus release of the Adaptive Agent Runtime. It
includes reproducibility boundaries for Codex invocation configuration and
production-ledger integration for preregistered provider studies.

## Highlights

- Attempt-scoped, immutable Codex invocation configuration with runtime-only
  authentication handling.
- Authoritative SQLite production ledger and checkpoint handoff for registered
  run plans.
- Provider-evidence classification and fail-closed infrastructure handling.

## Reliability / correctness fixes

- Production run plans now receive the SQLite ledger rather than an execution
  manifest.
- Provider-started metadata is derived from authoritative provider evidence.
- Release metadata now uses the repository's MIT license without deprecated
  setuptools license metadata.

## Testing and validation

The release candidate passed the canonical 275-test validator, clean-clone and
provider-free smoke workflows, wheel/sdist builds, clean artifact installation,
secret scanning, and portability checks.

## Experimental validation disclosure

V17/a001 was partial validation. It executed 82 registered provider requests:
32 tasks produced completed measurements, 48 ended in registered model-failure
states, 1 timed out, 1 encountered an infrastructure failure, and 80 remained
pending. The preserved evidence reconciles successfully, but the campaign did
not produce a complete 162-task validation or a final aggregate campaign score.

## Known limitations

- The full 162-task campaign has not completed successfully.
- Provider quotas or service failures may interrupt long-running campaigns.
- Long-running benchmark execution has substantial token and resource cost.
- Real provider wrappers remain experimental host-mode processes and do not yet
  have full provider filesystem/network sandboxing.
