# ARC 0.7 — Closed-Loop Review

ARC 0.7 connects persistent workers to GitHub pull-request review without changing ARC's source-of-truth model.

Highlights:

- publish/update a worker branch as a pull request through existing `gh` authentication;
- normalize CI checks, reviews, PR comments, and inline review comments;
- replay external review state as `session.review_*` events;
- route only new actionable feedback back into the owning worker;
- supervise all linked active workers with `arc supervise`;
- expose review state/actions in `arc`, `arc ui`, and scriptable CLI commands;
- preserve public multi-commit PR history while producing one exact synthetic squash candidate for the ARC gate;
- keep provider/GitHub credentials outside ARC state.

See [`CLOSED_LOOP_REVIEWS.md`](CLOSED_LOOP_REVIEWS.md) and [`INTERACTIVE_WORKSPACE.md`](INTERACTIVE_WORKSPACE.md).
