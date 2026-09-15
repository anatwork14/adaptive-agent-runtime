# V8 Subscription Capacity Forecast

This forecast is apparatus evidence only. It is not a V8 measurement and does
not assert a remaining subscription quota.

## Observed V5 sample

The preserved V5 result tree contains 18 completed measurements before the
capacity failure at Click / r003 / B7 / T001. The completed measurements report
provider-token telemetry but no billable cost (`cost_observed=false` and
`cost_usd=null` for every completed row).

| Quantity | Value |
|---|---:|
| Completed sample rows | 18 |
| Provider tokens, minimum | 358,673 |
| Provider tokens, median | 634,182.5 |
| Provider tokens, mean | 628,283.6667 |
| Provider tokens, p95 sample order statistic | 899,455 |
| Provider tokens, maximum | 967,034 |
| End-to-end time, mean | 176,546.7049 ms |
| End-to-end time, maximum | 490,393.1704 ms |
| Observed cost rows | 0 |

## V8 forecast

V8 contains 162 planned task executions (3 repositories × 6 repeats × 3
baselines × 3 tasks). Applying the observed mean only as an operational
forecast gives approximately 101,781,954 provider tokens and 7.94 hours of
serial provider time. A simple p95-per-row time scenario is approximately
9.98 hours serially. These are planning estimates, not guarantees.

The preregistered task budget gives a maximum arithmetic envelope of
162 × $2 = $324, below the $350 project cap. Subscription authentication is
not API billing: no token-to-dollar conversion is asserted, and no remaining
quota is invented. The capacity-readiness artifact records only observable
authentication/probe facts and the acknowledged V5 usage-limit risk.
