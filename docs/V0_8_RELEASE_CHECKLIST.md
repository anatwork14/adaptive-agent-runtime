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
- [ ] exact final PR CI green on Python 3.11 + 3.12
- [ ] squash merge to `main`
- [ ] post-merge `main` CI green

The last three items are release gates and must not be marked complete until GitHub verifies the exact merged revision.
