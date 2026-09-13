# ARC V5 — Context-policy multirepo apparatus-hardening campaign

V1 through V4 are closed. V4/a001 is preserved as a failed,
non-excludable apparatus attempt; it must not be rerun or treated as V4/a002.
V5 is a new parent-linked campaign whose scientific core is inherited from the
frozen V4 contract.

V5 makes one apparatus-only correction: the frozen Codex home, config path, and
config digest are propagated through the campaign executor into the nested
`benchmark run-plan` command and its execution-environment validator. The
outer campaign preflight and the nested run-plan boundary are qualified
separately. The nested qualification uses the real V5 command path and exits
after validation, before a runner or provider request is created.

The V4 failure and its scientific disposition are recorded in
`V4_POSTMORTEM.md`. The timeout boundary inherited from V4 is audited in
`V5_TIMEOUT_AUDIT.md`. `v4_to_v5_protocol_diff.json` records the apparatus-only
change, while `V4_V5_SCIENTIFIC_EQUIVALENCE.json` is generated only after the
normalized contract and all nine manifest comparisons pass.

V5 preserves the V4 repositories, commits, task sequence, hidden-test
digests, B3/B5/B7 treatment definitions, randomization, repeats, budgets,
provider/model/reasoning identity, Docker harnesses, timeouts, and exclusion
policy. Hidden tests remain external and are never copied into this campaign
directory or review package.

The canonical V5 freeze and any V5/a001 execution are intentionally not part
of this apparatus review. Authentication and provider qualification artifacts
must remain outside benchmark attempt directories and must not contain
credentials, tokens, cookies, or private keys.
