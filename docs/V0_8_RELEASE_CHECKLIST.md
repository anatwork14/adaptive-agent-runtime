# ARC 0.8 Release Checklist

- [x] tmux-backed provider runtime abstraction
- [x] persistent terminal CLI
- [x] runtime rediscovery after ARC restart
- [x] loopback-only worker previews
- [x] Workspace Preview controls
- [x] Workspace persistent Terminal controls
- [x] runtime mutation locking
- [x] runtime cleanup before worktree removal
- [x] runtime status replay after worktree cleanup
- [x] command metadata redaction
- [x] fake-tmux deterministic tests
- [x] Workspace runtime API tests
- [x] browser JavaScript syntax check
- [x] package version 0.8.0
- [x] README and runtime documentation
- [x] exact final PR CI green on Python 3.11 + 3.12 (`d199a8445cc39de7f740bb5a9cb284483871badd`)
- [x] squash merge to `main` (`30a3bf9245e2664f636d1fb0f152dbe87b2ac974`)
- [x] post-merge `main` CI green on Python 3.11 + 3.12
- [x] GitHub Pages deployment green from the v0.8 merge revision

ARC 0.8 passed all release gates. The original interactive-supervision gaps targeted by this milestone are complete; follow-up work belongs to security hardening, packaging, learned policies, and repository-scale evaluation.
