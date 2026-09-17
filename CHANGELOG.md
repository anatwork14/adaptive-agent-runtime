# Changelog

All notable software and apparatus changes are documented here. Research
campaign outcomes are reported separately and are not inferred from software
release history.

## [0.17.0] — 2026-09-17

### Highlights

- Added frozen Codex invocation configuration and attempt-scoped profile
  boundaries for reproducible provider-backed studies.
- Added production SQLite ledger, checkpoint, provider-evidence, and
  measurement handoff integration for preregistered run plans.

### Reliability / correctness

- Preserved one authoritative production-ledger path through initialization,
  run-plan handoff, resume, and checkpoint metadata.
- Added provider-started evidence transitions and fail-closed infrastructure
  handling for registered campaign execution.

### Testing and validation

- The canonical validator passed 275 tests, with two dependency deprecation
  warnings in the validation environment.
- Wheel and sdist builds, clean installation, provider-free smoke workflows,
  secret scanning, and package portability checks passed.

### Known limitations

- V17/a001 was partial validation, not a complete benchmark result: 32 tasks
  completed, 48 ended in registered model-failure states, 1 timed out, 1 had
  an infrastructure failure, and 80 remained pending.
- The campaign recorded 82 provider executions and has no final aggregate
  campaign score. Real provider wrappers remain experimental and host-mode.
