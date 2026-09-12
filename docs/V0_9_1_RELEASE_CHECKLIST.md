# ARC 0.9.1 Release Checklist

## Local browser control plane

- [x] `arc ui` rejects non-loopback bind hosts
- [x] `arc web` rejects non-loopback bind hosts
- [x] legacy `--allow-remote` no longer bypasses the local-only boundary
- [x] HTTP browser Origin validation on both control planes
- [x] WebSocket Origin validation before event-stream acceptance
- [x] arbitrary DNS aliases are not treated as localhost
- [x] local response hardening (`no-store`, `nosniff`, `no-referrer`)

## Compatibility and metadata

- [x] preserve ARC 0.9 least-privilege execution environment work
- [x] preserve `arc env-policy`
- [x] package version 0.9.1
- [x] Workspace/Mission Control derive version from distribution metadata
- [x] legacy `localhost-only` error wording contract remains compatible
- [x] CLI help states remote binding is disabled

## Documentation

- [x] public `SECURITY.md`
- [x] browser threat model in `docs/LOCAL_CONTROL_PLANE_SECURITY.md`
- [x] explicit distinction between browser security and 0.9 worker execution security

## Regression coverage

- [x] IPv4/IPv6 loopback classification
- [x] public/wildcard bind rejection
- [x] hostile HTTP Origin rejection
- [x] hostile WebSocket Origin rejection
- [x] non-browser clients without Origin remain supported
- [x] version metadata regression

## Release gates

- [ ] exact final branch push CI green on Python 3.11 + 3.12
- [ ] branch remains based on latest `main`
- [ ] independent pull-request CI green on the exact PR head
- [ ] squash merge with expected head SHA
- [ ] post-merge `main` CI green

Do not mark a release gate complete until GitHub verifies that exact revision.
