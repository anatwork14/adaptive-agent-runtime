# ARC Closed-Loop Reviews

ARC 0.7 adds an optional GitHub review loop for persistent worker sessions.

The boundary is deliberate:

> GitHub is an external review surface. ARC events, tasks, Git candidates, and gate outcomes remain authoritative.

## Requirements

- Git remote backed by GitHub;
- GitHub CLI (`gh`);
- an existing authenticated `gh` session;
- an open ARC `WorkerSession` with repository changes.

```bash
gh auth status
```

ARC never reads or stores the GitHub token itself.

## Publish a worker

```bash
arc session publish S_12345678
```

This commits the worker draft if needed, pushes `arc/task/<TASK>`, and creates a pull request. Re-running the command pushes the current worker branch and updates the existing PR linkage.

Interactive-shell equivalent:

```text
/publish
```

## Synchronize external state

```bash
arc session review S_12345678
```

ARC imports a normalized projection of:

- pull-request state;
- check/status rollup;
- review decision;
- general PR comments;
- inline review comments;
- merge-state status.

The normalized projection is emitted as `session.review_*` events.

## Apply feedback

```bash
arc session review S_12345678 --apply
```

or in the shell:

```text
/fix-review
```

Only new actionable feedback is routed into the worker. The worker prompt explicitly instructs the agent to inspect the real failure, preserve the task goal/acceptance criteria, and avoid weakening valid tests merely to make checks green.

## Supervise many linked workers

```bash
arc supervise
```

Automatically apply new actionable feedback:

```bash
arc supervise --auto-apply
```

Single pass:

```bash
arc supervise --once
arc supervise --once --auto-apply
```

The process itself is foreground/ephemeral; PR linkage and normalized state are replayable ARC events, so stopping/restarting supervision does not erase review state.

## Review event vocabulary

```text
session.pr_published
session.pr_updated
session.review_synced
session.review_feedback
session.review_feedback_applied
session.review_feedback_cleared
session.review_sync_failed
```

## Digest model

ARC uses two identities:

1. **snapshot digest** — hashes the normalized PR/check/review state and suppresses duplicate external-state events;
2. **actionable-feedback digest** — hashes only the actionable feedback text and prevents the same instruction being returned to a worker just because unrelated external state changed.

## Multi-commit PRs and the exact-candidate gate

Review iteration can create several commits. ARC does not rewrite that public history.

At final `session submit`, when the worker branch has multiple commits not reachable from integration HEAD, ARC creates an unattached synthetic squash commit:

```text
A -- B -- C     public review branch
 \________/
      │ complete branch tree
      ▼
      S           synthetic immutable candidate
```

`S` has:

- the current worker HEAD tree;
- the worker/integration merge-base as parent;
- no branch ref move or force push.

The normal IntegrationGate cherry-picks, verifies, and integrates `S`. This preserves both public review history and ARC's exact-candidate correctness contract.
