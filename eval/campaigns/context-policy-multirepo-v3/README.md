# ARC V3 — Context-policy multirepo campaign

This directory contains the proposed V3 campaign implementation. V3 preserves
the V2 scientific protocol and changes only the campaign identifiers plus ARC's
Git-hermetic commit apparatus. The V2 SSH-signing failure remains preserved in
`V2_POSTMORTEM.md`; V3 is not frozen and has no benchmark execution result.

Before any canonical freeze, the apparatus qualification must pass the ARC
suite, hostile Git configuration and identity-environment regressions, the
provider-free Docker workflow, and passive/active non-benchmark provider
qualification. `compare_v2_v3.py` must produce a passing scientific-equivalence
record.

The intended freeze command is `freeze_campaign.py`, and the intended runtime
boundary is `execute_campaign.py`. Neither is run by the V3 pre-freeze review.
The offline `finalize_campaign.py` is reserved for a successful future V3
attempt and performs no provider inference.
