# ARC 0.16.0

ARC 0.16.0 is a software/apparatus release of the Adaptive Agent Runtime. It packages the persistent multi-agent runtime, adaptive context/memory architecture, experiment harness, reproducibility infrastructure, tests, and documentation.

## Release basis

- Release line: `0.16.0`
- Release basis commit: `767f862fe8908598834654e4278fd65112845242`
- Python requirement: `>=3.11` (CI targets Python 3.11 and 3.12)
- License: MIT

The final release commit and checksums are recorded in the generated release manifest supplied with the release artifacts.

## Included capabilities

- Event-sourced authoritative state with replayable projections.
- Persistent isolated workers, task orchestration, adaptive context compilation, and provenance-aware memory.
- Supervised live provider turns with cancellation and redacted output handling.
- Git candidate isolation and serialized exact-candidate integration.
- Docker-backed command/test execution with documented limits.
- Preregistered B3/B5/B7 context-policy evaluation harnesses and hierarchical meta-analysis tooling.

## Research disclosure

| Campaign or apparatus stage | Status |
|---|---|
| V1 | CLOSED |
| V2 | CLOSED |
| V3 | CLOSED |
| V4 | CLOSED |
| V5 | CLOSED |
| V6 apparatus qualification | COMPLETED |
| V7 empirical attempt | INCOMPLETE / FORENSIC CLOSURE PENDING |

V7/a001 execution previously occurred on a remote execution environment. The campaign is incomplete. Original remote forensic evidence is currently unavailable locally. No final forensic classification has been independently completed from source evidence. No retry or V7/a002 has been performed. No V7 scientific conclusion is claimed.

Completed or partial campaign artifacts are not included in this software release. Private credentials, `auth.json`, tokens, private SSH material, hidden tests, private provider logs, and private forensic evidence are excluded.

## Validation scope

The release validation covers the local source checkout, package build, CLI help/version smoke checks, deterministic tests, lint/static checks configured by the project, documentation/link sanity, secret and large-file scans, license consistency, and repository hygiene. It does not execute V7 or any benchmark-provider execution.

## Installation

```bash
git clone https://github.com/anatwork14/adaptive-agent-runtime.git
cd adaptive-agent-runtime
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

See [README.md](README.md) and [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for usage and security boundaries.
