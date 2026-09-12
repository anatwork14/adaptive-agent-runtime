# ARC Review Event Contract

ARC 0.7 projects GitHub review state into the authoritative ARC event log without making GitHub authoritative project state.

| Event | Meaning |
|---|---|
| `session.pr_published` | Worker branch was pushed and linked to a new PR. |
| `session.pr_updated` | Existing linked PR branch was pushed again. |
| `session.review_synced` | A normalized external review snapshot changed. |
| `session.review_feedback` | New actionable feedback was observed. |
| `session.review_feedback_applied` | That actionable feedback was routed to the worker. |
| `session.review_feedback_cleared` | Previously pending actionable feedback is no longer present. |
| `session.review_sync_failed` | External synchronization failed; ARC task state is unchanged. |

The review snapshot records check names/statuses/conclusions, review decision, merge-state status, PR identity and digests. Credentials are never written into these events.

The snapshot digest identifies normalized external state. The feedback digest identifies actionable instructions independently so non-actionable GitHub state churn does not repeatedly trigger the same worker turn.
