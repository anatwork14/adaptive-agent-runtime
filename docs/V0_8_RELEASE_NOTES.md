# ARC 0.8 — Persistent PTY & Worker Preview

ARC 0.8 completes the local interactive-worker loop introduced in v0.6 and extended with closed-loop GitHub review in v0.7.

Highlights:

- optional tmux-backed provider terminals that survive the invoking ARC command;
- replayable runtime metadata rather than persisted PIDs;
- worker application previews bound to loopback only;
- separate browser origin for preview content;
- Preview and persistent Terminal controls in `arc ui`;
- runtime output tails and readiness projection;
- per-worker runtime mutation locking;
- managed runtime shutdown before worktree cleanup;
- deterministic fake-tmux CI coverage;
- runtime state reconstruction across ARC application restarts.

Project correctness remains unchanged: only an exact candidate accepted by the ARC IntegrationGate becomes integrated project state.
