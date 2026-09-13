# ARC Git-Hermeticity Design

## Boundary

ARC owns the candidate and integration commits created after a provider exits.
Those operations must be independent of user repository/global signing policy.
The user's global Git configuration is read-only from ARC's perspective and is
never rewritten.

## Command contract

`runtime.git.arc_git_write_args()` prefixes each ARC-controlled commit-producing
operation with:

```text
-c user.name=<deterministic ARC identity>
-c user.email=<deterministic ARC identity>
-c commit.gpgsign=false
```

The helper is applied to:

| Operation | Identity |
|---|---|
| regular candidate `git commit` | `ARC Agent <arc@local>` |
| multi-commit candidate `git commit-tree` squash | `ARC Agent <arc@local>` |
| gate worktree candidate cherry-pick | `ARC Gate <arc-gate@local>` |
| final integration cherry-pick | `ARC Gate <arc-gate@local>` |

`cherry-pick --abort`, status, inspection, worktree creation/removal, and other
non-commit operations remain ordinary Git commands. ARC does not disable
signing globally, edit `.gitconfig`, retag images, or access the user's signing
key.

## Hostile-host regression

The permanent integration regression injects, only into the test subprocesses:

```text
commit.gpgsign=true
gpg.format=ssh
user.signingkey=<missing noninteractive key>
GIT_TERMINAL_PROMPT=0
```

It first runs the legacy unscoped candidate commit and requires the signing
failure. It then runs the real WorktreeManager and IntegrationGate paths and
requires a candidate commit, `task.submitted`, gate acceptance, deterministic
candidate/gate identities, and an unchanged global Git configuration snapshot.
The multi-commit squash path is covered separately.

## Scope and non-goals

This hardening changes only ARC's internal Git plumbing. It does not modify
benchmark repository commits, hidden tests, campaign treatment logic, Docker
images, provider configuration, or V1/V2 artifacts.

