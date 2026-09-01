# ADR-0002: Paired platform and runtime release

- Status: accepted for alpha scaffold
- Date: 2026-09-01

## Context

Independent application and core upgrades created compatibility bridges and
allowed operators to stage only half of an intended product release. Recovery
still benefits from independently signed components.

## Decision

The ordinary v3 release is one signed universal container binding exact native
platform and MicroPython runtime components. Components remain independently
signed, but the device stages, trials, confirms or rolls back the required pair
as one product transaction.

## Consequences

- Operators see one upgrade and one version.
- Factory/recovery tools can still install a verified component deliberately.
- Trial state and configuration migration must retain enough information to
  restore the previous confirmed pair atomically.
