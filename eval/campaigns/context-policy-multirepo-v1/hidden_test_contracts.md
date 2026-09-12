# Private Hidden-Test Contracts

The exact test code and concrete edge-case values are private. These contracts are public so agents receive the intended behavior and exact new API surface without seeing grader implementation details.

## Click

### T001 — sensitive parameter metadata
- `Parameter`, `Option`, and the decorator plumbing accept an opt-in `sensitive: bool = False` contract; T001 is exercised through options.
- marking an option sensitive must not change parsing, defaults, callbacks, help text, or invocation values.
- `to_info_dict()` exposes the boolean as `sensitive`.

### T002 — context parameter snapshot
- add `Context.parameter_snapshot(*, redact_sensitive: bool = True) -> list[dict[str, object]]`.
- the snapshot is deterministic and does not mutate context or parameters.
- each record contains `name`, `value`, `source`, and `sensitive`.
- `source` is the `ParameterSource.name` string or `None`.
- sensitive values are the literal `<redacted>` when `redact_sensitive=True`; setting it false returns raw values.
- command-line, environment, default-map and default sources remain distinguishable.

### T003 — generalization
- `Argument(..., sensitive=True)` and decorator-created arguments use the same base-`Parameter` contract as options.
- existing option behavior from T001/T002 remains unchanged.
- snapshots redact sensitive arguments and options identically.

## HTTPX

### T001 — header redaction primitive
- add `Headers.redacted() -> Headers`.
- the case-insensitive default sensitive set covers `Authorization`, `Proxy-Authorization`, `Cookie`, and `Set-Cookie`.
- returned headers are independent; input headers are not mutated.
- header order and duplicate multiplicity are preserved.
- non-sensitive names and values are unchanged.

### T002 — verbose request rendering
- add CLI flag `--show-sensitive`, default false.
- normal verbose output never reveals default sensitive request-header values.
- `--show-sensitive` restores the previous raw verbose request-header rendering.
- HTTP/1.1 and HTTP/2 request-line/header formatting remains otherwise unchanged.

### T003 — verbose response rendering
- default verbose response output redacts sensitive response headers, especially `Set-Cookie`.
- the same `--show-sensitive` flag restores raw rendering.
- body rendering and unrelated response behavior are unchanged.

## python-dotenv

### T001 — raw entry provenance
- add immutable public `DotEnvEntry` with fields `key: str`, `value: Optional[str]`, and `line: int`.
- add `DotEnv.entries() -> Iterator[DotEnvEntry]` for valid keyed bindings before interpolation.
- comments/blank/error-only bindings do not appear as keyed entries.
- parsing semantics are unchanged.

### T002 — resolved metadata API
- add top-level `dotenv_values_with_metadata(...) -> OrderedDict[str, DotEnvEntry]` and export it from `dotenv`.
- arguments and discovery/encoding behavior mirror `dotenv_values()` where applicable.
- values use the same interpolation and override semantics as `dotenv_values()`.
- duplicate keys use the same winning value as existing behavior and retain the winning binding's source line.
- keys without a value remain distinguishable from empty strings.

### T003 — CLI JSON metadata
- extend `dotenv list --format` with exact choice `json-meta`.
- `json-meta` emits a JSON object mapping each key to `{ "value": ..., "line": ... }`.
- output is deterministic/sorted and valid JSON.
- all pre-existing list formats remain behaviorally unchanged.
