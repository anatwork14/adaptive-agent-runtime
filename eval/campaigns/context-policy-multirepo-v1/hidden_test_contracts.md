# Private Hidden-Test Contracts

The exact test code and concrete edge-case values are private. These contracts are public so agents receive the intended behavior without seeing grader implementation details.

## Click

### T001 — sensitive parameter metadata
- `sensitive` is opt-in and defaults false.
- Marking a parameter sensitive must not change parsing, defaults, callbacks, help text, or invocation values.
- introspection/info dictionaries expose the sensitivity bit.

### T002 — context parameter snapshot
- snapshot is deterministic and does not mutate context or parameters.
- each record contains parameter name, current value, source name or null, and sensitivity.
- sensitive values are the literal `<redacted>` unless explicitly requesting raw values.
- command-line, environment, default-map and default sources remain distinguishable.

### T003 — generalization
- both options and arguments can be sensitive through one base-parameter contract.
- existing option behavior from T001/T002 remains unchanged.
- snapshots redact sensitive arguments and options identically.

## HTTPX

### T001 — header redaction primitive
- case-insensitive default sensitive set covers `Authorization`, `Proxy-Authorization`, `Cookie`, and `Set-Cookie`.
- output is independent; input headers are not mutated.
- header order and duplicate multiplicity are preserved.
- non-sensitive names and values are unchanged.

### T002 — verbose request rendering
- normal verbose output never reveals default sensitive request-header values.
- an explicit unsafe opt-out restores raw rendering.
- HTTP/1.1 and HTTP/2 request-line/header formatting remains otherwise unchanged.

### T003 — verbose response rendering
- default verbose response output redacts sensitive response headers, especially `Set-Cookie`.
- the same explicit unsafe opt-out restores raw rendering.
- body rendering and unrelated response behavior are unchanged.

## python-dotenv

### T001 — raw entry provenance
- public immutable entries expose key, raw value, and 1-based source line.
- comments/blank/error-only bindings do not appear as keyed entries.
- parsing semantics are unchanged.

### T002 — resolved metadata API
- values use the same interpolation and override semantics as `dotenv_values()`.
- duplicate keys use the same winning value as existing behavior and retain the winning binding's source line.
- keys without a value remain distinguishable from empty strings.

### T003 — CLI JSON metadata
- a new metadata JSON format exposes `{value, line}` for each key.
- output is deterministic/sorted and valid JSON.
- all pre-existing list formats remain behaviorally unchanged.
