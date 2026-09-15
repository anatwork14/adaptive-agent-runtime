# Context-policy multirepo V12 implementation plan

V11 is closed and remains immutable. V12 is a new operational-repair
generation branched from V11 at `476ecf135910b53301f821fb401a7e3362ff83dc`.

## Contract

- Preserve the V11 scientific design and provider/config/Docker identity.
- Start V12 with exactly 162 `PENDING` logical tasks and zero observations.
- Keep V11 evidence outside V12 ledgers and score inputs.

## Repair order

1. Define structured provider-evidence precedence and side-effect retry gate.
2. Make the integrated SQLite `logical_tasks`/`execution_instances` ledger
   authoritative, with atomic checkpoint advancement.
3. Continue after task-level model/provider outcomes; stop only for protocol,
   ledger, sandbox, configuration, or unrecoverable infrastructure defects.
4. Require durable measurement export/reference before `COMPLETED`.
5. Validate interruption after persistence, recovery before persistence, retry
   bounds, completeness, request/instance bijection, and the V11 regression.
6. Run the temporary five-task production simulation, then freeze once and run
   read-only post-freeze reconstruction/preflight.

## Stop conditions

Any scientific/configuration drift, missing logical registration, duplicate
request mapping, unsafe retry, lost evidence, duplicate terminal transition,
fail-fast task handling, or provider request during qualification stops the
campaign and yields no V12 sign-off.
