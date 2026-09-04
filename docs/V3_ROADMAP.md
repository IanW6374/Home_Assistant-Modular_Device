# IoT-MD v3 alpha roadmap

Milestones are capability gates, not calendar commitments. A milestone cannot
advance because its version label exists; its listed evidence must pass.

## Alpha 0 — architecture and contracts

- Approve requirements, native/runtime ownership and security invariants.
- Establish executable ABI schemas and alpha-only CI.
- Select the MicroPython and ESP-IDF evaluation matrix without changing v2.
- Define partition, paired-release and v2 rollback constraints.

Exit: contract checks pass and architecture decisions are accepted.

## Alpha 1 — recoverable native platform

- Boot a minimal secure ESP-IDF platform on ESP32-S3 N8R8.
- Expose ABI/version/capability and bounded boot-health records.
- Embed MicroPython without loading a product runtime.
- Enter recovery and install a signed test platform after runtime failure.

Exit: repeated boot, watchdog, corrupt-runtime and recovery HIL tests pass.

Current status: `3.0.0-alpha.1` implements the first native capability ABI and
validated MicroPython adapter on the qualified v2.5 toolchain. It is a boundary
test candidate, not completion of the Alpha 1 exit gate; native recovery
ownership and its HIL fault matrix remain to be implemented.

## Alpha 2 — storage and paired updates

- Implement encrypted namespace handles and transactional storage.
- Implement paired native/runtime staging, trial, confirmation and rollback.
- Build one universal host artifact with SBOM and provenance.
- Prove power-interruption recovery at every update transition.

Exit: no interruption produces an unrecoverable or unconfirmed mixed pair.

Current status: `3.0.0-alpha.2` implements ABI 2 encrypted transactional
namespace snapshots and the runtime paired-release state machine. Host tests
cover interruption at every state-record transition. Native partition-pair
trial selection, automatic rollback and the corresponding hardware power-cut
matrix remain open; capability reporting therefore continues to mark paired
trial and native rollback unavailable.

## Alpha 3 — application kernel and one reference module

- Add configuration schema/migrations, service registry and task supervisor.
- Add resource allocation across the platform ABI.
- Port one simple sensor as the reference driver and contract-test fixture.
- Expose bounded health, event and support snapshots.

Exit: the reference module survives restart, configuration failure and resource
conflict tests without compromising recovery.

## Alpha 4 — product transports

- Port MQTT, server-rendered portal and mTLS Device API over Wi-Fi.
- Generate portal forms/navigation from shared metadata.
- Add unified DNS/time/TLS/MQTT/CA/syslog/release connectivity diagnostics.
- Keep service contracts independent of transport adapters.

Exit: portal/API/MQTT behavior and security match the v3 requirements baseline.

## Alpha 5 — identity, fleet and v2 migration

- Port certificate enrollment/renewal and trust administration.
- Add fleet inventory, signed policy and canary reporting.
- Import a v2 complete backup through previewed transactional migration.
- Port the supported v2.5 driver set through the reference driver contract.

Exit: representative v2 devices migrate, roll back and retry without losing
their confirmed v2 state.

## Beta — operational qualification

- Multi-day soak, storage pressure, certificate renewal and network fault tests.
- Repeated production-secure universal upgrades and power interruption.
- Fleet canary rollout and automated pause on health thresholds.
- Documentation, accessibility, API and support workflows complete.

Stable promotion requires reproducible clean-source artifacts, complete HIL
evidence and no dependency on an experimental transport.
