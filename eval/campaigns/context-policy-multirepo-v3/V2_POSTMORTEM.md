# V2/a001 Postmortem

This document records the preserved V2 apparatus failure. It does not modify or
reinterpret any V1 or V2 scientific artifact.

## Classification

```text
campaign       = context-policy-multirepo-v2
attempt        = a001
status         = FAILED
classification = NON_EXCLUDABLE_FAILURE
replacement    = NO
```

## Observed provider boundary

The preserved execution record shows that the provider request, response, and
completion boundaries were observed before the failure:

```text
provider request observed   = yes
provider response observed  = yes
provider completion observed = yes
```

The failure occurred after provider execution, while ARC was creating the
immutable candidate commit.

## Failure and root cause

```text
failure stage = candidate commit creation after agent/provider execution

root cause = the host Git configuration required SSH commit signing, while the
             ARC-internal candidate commit command did not disable signing
```

The preserved error requested the passphrase for
`/Users/teobun/.ssh/id_rsa` and then reported `fatal: failed to write commit
object`. This is an apparatus failure, not a provider outage or a host failure
before the first provider turn.

## Scientific consequence

```text
scientific result = unavailable
```

This failure is not evidence for or against B3, B5, or B7. No V2 comparative
campaign result is validly available, and the frozen exclusion policy permits
no replacement attempt.

